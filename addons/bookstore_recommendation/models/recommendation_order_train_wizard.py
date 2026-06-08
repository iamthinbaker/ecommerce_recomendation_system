import os

import pandas as pd

from odoo import _, api, fields, models

from ..engine.recomendation_order_engine import OrderRecommendationEngine

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "models")
_ORDER_MODEL_PATH = os.path.join(_MODELS_DIR, "order_copurchase.json")


class RecommendationOrderTrainWizard(models.TransientModel):
    _name = "recommendation.order.train.wizard"
    _description = "Train User Recommendation Model"

    # ── Filtros ──────────────────────────────────────────────────────────────
    months_lookback = fields.Integer(
        string="Últimos N meses",
        default=12,
        help="Solo pedidos de los últimos N meses. 0 = sin límite temporal.",
    )
    min_orders = fields.Integer(
        string="Pedidos mínimos por usuario",
        default=1,
        help="Excluye usuarios con menos de N pedidos confirmados en el periodo.",
    )
    require_recurrence = fields.Boolean(
        string="Solo usuarios con recurrencia",
        default=False,
        help="Si está activo, solo se incluyen usuarios con 2 o más pedidos (equivale a "
        "Pedidos mínimos ≥ 2).",
    )

    # ── Estado ───────────────────────────────────────────────────────────────
    user_model_status = fields.Char(
        string="User Model Status",
        readonly=True,
        default="Not trained yet",
    )
    last_trained = fields.Datetime(
        string="Last Trained",
        readonly=True,
    )

    # ── Computed helpers ─────────────────────────────────────────────────────
    effective_min_orders = fields.Integer(
        string="Pedidos mínimos efectivos",
        compute="_compute_effective_min_orders",
        help="Valor real de pedidos mínimos que se usará al entrenar.",
    )

    @api.depends("min_orders", "require_recurrence")
    def _compute_effective_min_orders(self):
        for rec in self:
            rec.effective_min_orders = max(
                rec.min_orders, 2 if rec.require_recurrence else 1
            )

    # ── Acción ───────────────────────────────────────────────────────────────
    def action_train_user_model(self):
        self.ensure_one()
        rows = self.env["recommendation.engine.order"]._get_order_baskets(
            months=self.months_lookback or None,
            min_product_orders=self.effective_min_orders,
        )

        if not rows:
            self.user_model_status = _("Training failed — not enough data")
            return self._reopen()

        df = pd.DataFrame(rows, columns=["order_id", "product_id"])
        OrderRecommendationEngine().train(df).save_model(_ORDER_MODEL_PATH)

        self.user_model_status = _("Trained successfully")
        self.last_trained = fields.Datetime.now()
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
