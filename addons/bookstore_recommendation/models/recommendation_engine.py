import numpy as np
import pandas as pd

from odoo import api, models


class RecommendationEngineBase(models.AbstractModel):
    _name = "recommendation.engine.base"
    _description = "Recommendation Engine Base"

    @api.model
    def _get_purchase_data(self, months=None, min_user_orders=1, min_product_orders=1):
        params = {
            'min_user_orders': max(int(min_user_orders), 1),
            'min_product_orders': max(int(min_product_orders), 1),
        }

        date_filter = ""
        subq_date = ""
        if months:
            params['months'] = int(months)
            date_filter = "AND so.date_order  >= NOW() - INTERVAL '1 month' * %(months)s"
            subq_date   = "AND so2.date_order >= NOW() - INTERVAL '1 month' * %(months)s"

        query = f"""
            SELECT
                so.partner_id,
                pt.id AS product_tmpl_id,
                SUM(sol.product_uom_qty) AS qty
            FROM sale_order_line sol
            JOIN sale_order      so  ON so.id  = sol.order_id
            JOIN product_product pp  ON pp.id  = sol.product_id
            JOIN product_template pt ON pt.id  = pp.product_tmpl_id
            WHERE so.state IN ('sale', 'done')
              AND sol.product_id IS NOT NULL
              {date_filter}
              AND so.partner_id IN (
                  SELECT so2.partner_id
                  FROM   sale_order so2
                  WHERE  so2.state IN ('sale', 'done')
                  {subq_date}
                  GROUP  BY so2.partner_id
                  HAVING COUNT(DISTINCT so2.id) >= %(min_user_orders)s
              )
              AND pt.id IN (
                  SELECT pt2.id
                  FROM   sale_order_line sol2
                  JOIN   product_product  pp2 ON pp2.id = sol2.product_id
                  JOIN   product_template pt2 ON pt2.id = pp2.product_tmpl_id
                  JOIN   sale_order       so2 ON so2.id = sol2.order_id
                  WHERE  so2.state IN ('sale', 'done')
                  {subq_date}
                  GROUP  BY pt2.id
                  HAVING COUNT(DISTINCT so2.id) >= %(min_product_orders)s
              )
            GROUP BY so.partner_id, pt.id
        """
        self.env.cr.execute(query, params)
        return self.env.cr.fetchall()

    @api.model
    def _build_user_item_matrix(self, months=None, min_user_orders=1, min_product_orders=1):
        rows = self._get_purchase_data(
            months=months,
            min_user_orders=min_user_orders,
            min_product_orders=min_product_orders,
        )
        if not rows:
            return None

        return (
            pd.DataFrame(
                rows,
                columns=["partner_id", "product_id", "qty"],
            )
            .pivot_table(
                index="partner_id",
                columns="product_id",
                values="qty",
                aggfunc="sum",
                fill_value=0,
            )
            .astype(np.float32)
        )
