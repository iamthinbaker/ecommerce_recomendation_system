import json
import logging
import os

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

from odoo import api, models

_logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "models")
_USER_MODEL_PATH = os.path.join(_MODELS_DIR, "user_copurchase.json")


class UserRecommendationEngine(models.AbstractModel):
    _name = "recommendation.engine.user"
    _inherit = "recommendation.engine.base"
    _description = "Co-Purchase Recommendation Engine (Also Bought)"

    @api.model
    def _get_order_baskets(self, months=None, min_product_orders=1):
        """
        Returns (order_id, product_template_id) rows for confirmed orders,
        filtered to products that appear in at least min_product_orders distinct orders.
        """
        params = {"min_product_orders": max(int(min_product_orders), 1)}
        date_filter = ""
        if months:
            params["months"] = int(months)
            date_filter = "AND so.date_order >= NOW() - INTERVAL '1 month' * %(months)s"

        self.env.cr.execute(
            f"""
            SELECT so.id AS order_id, pt.id AS product_tmpl_id
            FROM sale_order_line sol
            JOIN sale_order      so  ON so.id  = sol.order_id
            JOIN product_product pp  ON pp.id  = sol.product_id
            JOIN product_template pt ON pt.id  = pp.product_tmpl_id
            WHERE so.state IN ('sale', 'done')
              AND sol.product_id IS NOT NULL
              {date_filter}
              AND pt.id IN (
                  SELECT pt2.id
                  FROM sale_order_line sol2
                  JOIN product_product  pp2 ON pp2.id = sol2.product_id
                  JOIN product_template pt2 ON pt2.id = pp2.product_tmpl_id
                  JOIN sale_order       so2 ON so2.id = sol2.order_id
                  WHERE so2.state IN ('sale', 'done') {date_filter}
                  GROUP BY pt2.id HAVING COUNT(DISTINCT so2.id) >= %(min_product_orders)s
              )
            GROUP BY so.id, pt.id
            """,
            params,
        )
        return self.env.cr.fetchall()

    @api.model
    def _build_copurchase_matrix(self, months=None, min_product_orders=1):
        """
        Builds a product × product cosine-similarity matrix from basket co-occurrences.

        Each order is treated as a binary basket (1 = product present).
        The resulting matrix captures how often two products are bought together,
        normalised so that popular products don't dominate.

        Example:
        ---
        >>> self._build_copurchase_matrix(months=12, min_product_orders=2)
        product_id    42     57     89
        product_id
        42           0.00   0.71   0.50
        57           0.71   0.00   0.35
        89           0.50   0.35   0.00
        """
        rows = self._get_order_baskets(months=months, min_product_orders=min_product_orders)
        if not rows:
            return None

        basket = (
            pd.DataFrame(rows, columns=["order_id", "product_id"])
            .assign(bought=1)
            .pivot_table(
                index="order_id",
                columns="product_id",
                values="bought",
                aggfunc="max",
                fill_value=0,
            )
            .astype(np.float32)
        )

        if basket.shape[0] < 2 or basket.shape[1] < 2:
            return None

        sim = cosine_similarity(basket.T)
        np.fill_diagonal(sim, 0.0)
        return pd.DataFrame(sim, index=basket.columns, columns=basket.columns)

    @api.model
    def _train_user_model(self, months=None, min_user_orders=1):
        """
        Trains the co-purchase model.
        min_user_orders is reused here as the minimum number of orders a product
        must appear in to be included in the matrix.
        """
        sim_df = self._build_copurchase_matrix(
            months=months,
            min_product_orders=min_user_orders,
        )
        if sim_df is None:
            _logger.warning("Not enough co-purchase data to train model.")
            return False

        os.makedirs(_MODELS_DIR, exist_ok=True)
        top_k = 50
        sparse = {
            int(pid): {
                int(nid): round(float(score), 5)
                for nid, score in sim_df[pid].nlargest(top_k).items()
                if score > 0
            }
            for pid in sim_df.columns
        }
        with open(_USER_MODEL_PATH, "w") as f:
            json.dump(sparse, f)

        _logger.info("Co-purchase model trained: %d products.", sim_df.shape[0])
        return True

    @api.model
    def _load_user_model(self):
        try:
            with open(_USER_MODEL_PATH) as f:
                raw = json.load(f)
            return {int(k): {int(nk): v for nk, v in neighbors.items()} for k, neighbors in raw.items()}
        except Exception as exc:
            _logger.error("Failed to load co-purchase model: %s", exc)
            return None

    @api.model
    def get_user_recommendations(self, order_id, limit=6):
        """
        Given a sale order, returns products frequently co-purchased with the
        items currently in the cart, excluding products already in it.
        Falls back to popular products if the cart has no coverage in the model.
        """
        sim_df = self._load_user_model()
        if sim_df is None:
            return self.env["product.template"]

        order = self.env["sale.order"].browse(order_id)
        if not order.exists():
            return self._get_popular_products(limit=limit)

        cart_tmpl_ids = order.order_line.mapped("product_id.product_tmpl_id.id")
        if not cart_tmpl_ids:
            return self._get_popular_products(limit=limit)

        model = sim_df  # now a dict[int, dict[int, float]]
        in_matrix = [pid for pid in cart_tmpl_ids if pid in model]
        if not in_matrix:
            return self._get_popular_products(limit=limit)

        cart_set = set(cart_tmpl_ids)
        score_acc = {}
        for pid in in_matrix:
            for neighbor_id, score in model[pid].items():
                if neighbor_id not in cart_set:
                    score_acc[neighbor_id] = score_acc.get(neighbor_id, 0.0) + score

        if not score_acc:
            return self._get_popular_products(limit=limit)

        top_ids = sorted(score_acc, key=score_acc.__getitem__, reverse=True)[:limit]

        return (
            self.env["product.template"]
            .browse(top_ids)
            .filtered(lambda p: p.website_published)[:limit]
        )

    @api.model
    def _get_popular_products(self, limit=6):
        self.env.cr.execute(
            """
            SELECT pt.id, SUM(sol.product_uom_qty) AS total
            FROM sale_order_line sol
            JOIN product_product pp ON pp.id = sol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN sale_order so ON so.id = sol.order_id
            WHERE so.state IN ('sale', 'done')
            GROUP BY pt.id
            ORDER BY total DESC
            LIMIT %s
            """,
            (limit,),
        )
        ids = [r[0] for r in self.env.cr.fetchall()]
        return (
            self.env["product.template"]
            .browse(ids)
            .filtered(lambda p: p.website_published)
        )
