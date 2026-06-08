import os

import pandas as pd

from odoo import _, fields, models

from ..engine.recomentation_item_engine import ItemRecommendationEngine

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "models")
_ITEM_MODEL_PATH = os.path.join(_MODELS_DIR, "item_similarity.json")


class RecommendationItemTrainWizard(models.TransientModel):
    _name = "recommendation.item.train.wizard"
    _description = "Train Item Recommendation Model"

    # ── Filtros ──────────────────────────────────────────────────────────────
    min_product_orders = fields.Integer(
        string="Apariciones mínimas por producto",
        default=1,
        help="Excluye productos que aparecen en menos de N pedidos confirmados.",
    )

    # ── Atributos del producto ────────────────────────────────────────────────
    use_parent_genre = fields.Boolean(string="Género principal", default=True)
    use_genre = fields.Boolean(string="Género", default=True)
    use_sub_genre = fields.Boolean(string="Subgénero", default=True)
    use_author = fields.Boolean(string="Autor", default=True)
    use_publisher = fields.Boolean(string="Editorial", default=True)
    use_description = fields.Boolean(string="Descripción", default=False)
    use_year = fields.Boolean(string="Año de publicación", default=False)
    use_pages = fields.Boolean(string="Número de páginas", default=False)
    use_price = fields.Boolean(string="Precio", default=False)

    # ── Estado ───────────────────────────────────────────────────────────────
    item_model_status = fields.Char(
        string="Item Model Status",
        readonly=True,
        default="Not trained yet",
    )
    last_trained = fields.Datetime(
        string="Last Trained",
        readonly=True,
    )

    # ── Acción ───────────────────────────────────────────────────────────────
    def action_train_item_model(self):
        self.ensure_one()

        if not any(
            [
                self.use_parent_genre,
                self.use_genre,
                self.use_sub_genre,
                self.use_author,
                self.use_publisher,
                self.use_description,
                self.use_year,
                self.use_pages,
                self.use_price,
            ]
        ):
            self.item_model_status = _(
                "Training failed — select at least one attribute"
            )
            return self._reopen()

        products = self.env["product.template"].sudo().search([("is_book", "=", True)])

        if len(products) < 2:
            self.item_model_status = _("Training failed — not enough data")
            return self._reopen()

        attribute_map = {
            "parent_genre": (
                self.use_parent_genre,
                lambda p: p.book_genre_id.parent_id.name or "",
            ),
            "genre": (self.use_genre, lambda p: str(p.book_genre_id.id or "")),
            "sub_genre": (
                self.use_sub_genre,
                lambda p: str(p.book_sub_genre_id.id or ""),
            ),
            "author": (self.use_author, lambda p: p.book_author or ""),
            "publisher": (self.use_publisher, lambda p: p.book_publisher or ""),
            "description": (self.use_description, lambda p: p.description_sale or ""),
            "year": (self.use_year, lambda p: float(p.book_year or 0)),
            "pages": (self.use_pages, lambda p: float(p.book_pages or 0)),
            "price": (self.use_price, lambda p: float(p.list_price or 0)),
        }

        df = pd.DataFrame(
            [
                {
                    "id": p.id,
                    **{
                        attr: fn(p)
                        for attr, (enabled, fn) in attribute_map.items()
                        if enabled
                    },
                }
                for p in products
            ]
        )

        ItemRecommendationEngine().train(df).save_model(_ITEM_MODEL_PATH)

        self.item_model_status = _("Trained successfully")
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
