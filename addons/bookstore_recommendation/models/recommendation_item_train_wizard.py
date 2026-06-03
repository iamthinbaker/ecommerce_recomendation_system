from odoo import _, fields, models


class RecommendationItemTrainWizard(models.TransientModel):
    _name = 'recommendation.item.train.wizard'
    _description = 'Train Item Recommendation Model'

    # ── Filtros ──────────────────────────────────────────────────────────────
    months_lookback = fields.Integer(
        string='Últimos N meses',
        default=12,
        help='Solo pedidos de los últimos N meses. 0 = sin límite temporal.',
    )
    min_product_orders = fields.Integer(
        string='Apariciones mínimas por producto',
        default=1,
        help='Excluye productos que aparecen en menos de N pedidos confirmados en el periodo.',
    )

    # ── Estado ───────────────────────────────────────────────────────────────
    item_model_status = fields.Char(
        string='Item Model Status',
        readonly=True,
        default='Not trained yet',
    )
    last_trained = fields.Datetime(
        string='Last Trained',
        readonly=True,
    )

    # ── Acción ───────────────────────────────────────────────────────────────
    def action_train_item_model(self):
        self.ensure_one()
        engine = self.env['recommendation.engine.item']
        success = engine._train_item_model(
            months=self.months_lookback or None,
            min_product_orders=self.min_product_orders,
        )
        if success:
            self.item_model_status = _('Trained successfully')
            self.last_trained = fields.Datetime.now()
        else:
            self.item_model_status = _('Training failed — not enough data')
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
