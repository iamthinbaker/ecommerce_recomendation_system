import logging
import os

import pandas as pd

from odoo import api, models

from ..engine.recomendation_order_engine import OrderRecommendationEngine

_logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "models")
_ORDER_MODEL_PATH = os.path.join(_MODELS_DIR, "order_copurchase.json")


class OrderRecommendationEngineModel(models.AbstractModel):
    _name = "recommendation.engine.order"
    _inherit = "recommendation.engine.base"
    _description = "Co-Purchase Recommendation Engine (Also Bought)"

    @api.model
    def _get_order_baskets(self, months=None, min_product_orders=1, date_from=None):
        """
        Returns (order_id, product_template_id) rows for confirmed orders,
        filtered to products that appear in at least min_product_orders distinct orders.
        """
        params = {"min_product_orders": max(int(min_product_orders), 1)}
        date_filter = ""
        if date_from:
            params["date_from"] = date_from
            date_filter = "AND so.date_order >= %(date_from)s"
        elif months:
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
    def _train_order_model(self, months=None, min_product_orders=1):
        rows = self._get_order_baskets(months=months, min_product_orders=min_product_orders)
        if not rows:
            _logger.warning("Not enough co-purchase data to train model.")
            return False

        df = pd.DataFrame(rows, columns=["order_id", "product_id"])
        engine = OrderRecommendationEngine()
        engine.train(df)
        engine.save_model(_ORDER_MODEL_PATH)

        _logger.info("Co-purchase model trained: %d products.", engine.similarity_df.shape[0])
        return True

    @api.model
    def _load_order_model(self):
        try:
            return OrderRecommendationEngine.load_model(_ORDER_MODEL_PATH)
        except Exception as exc:
            _logger.error("Failed to load co-purchase model: %s", exc)
            return None

    @api.model
    def get_order_recommendations(self, order_id, limit=6):
        """
        Given a sale order, returns products frequently co-purchased with the
        items currently in the cart, excluding products already in it.
        Falls back to popular products if the cart has no coverage in the model.
        """
        engine = self._load_order_model()
        if engine is None:
            return self.env["product.template"]

        order = self.env["sale.order"].browse(order_id)
        if not order.exists():
            return self._get_popular_products(limit=limit)

        cart_tmpl_ids = order.order_line.mapped("product_id.product_tmpl_id.id")
        sample = pd.DataFrame({"product_id": cart_tmpl_ids or []})
        top_ids = list(engine.predict(sample, limit=limit).index)

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
