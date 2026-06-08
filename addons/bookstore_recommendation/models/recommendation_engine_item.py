import logging
import os

import pandas as pd

from odoo import api, models

from ..engine.recomentation_item_engine import ItemRecommendationEngine

_logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "models")
_ITEM_MODEL_PATH = os.path.join(_MODELS_DIR, "item_similarity.json")


class ItemRecommendationEngineModel(models.AbstractModel):
    _name = "recommendation.engine.item"
    _inherit = "recommendation.engine.base"
    _description = "Item-Based Recommendation Engine"

    @api.model
    def _train_item_model(
        self,
        months=None,
        min_product_orders=1,
        use_parent_genre=True,
        use_genre=True,
        use_sub_genre=True,
        use_author=True,
        use_publisher=True,
        use_description=False,
        use_year=False,
        use_pages=False,
        use_price=False,
    ):
        products = self.env["product.template"].sudo().search([("is_book", "=", True)])

        if len(products) < 2:
            _logger.warning("Not enough products to train item model.")
            return False

        attribute_map = {
            "parent_genre": (use_parent_genre, lambda p: p.book_genre_id.parent_id.name or ""),
            "genre": (use_genre, lambda p: str(p.book_genre_id.id or "")),
            "sub_genre": (use_sub_genre, lambda p: str(p.book_sub_genre_id.id or "")),
            "author": (use_author, lambda p: p.book_author or ""),
            "publisher": (use_publisher, lambda p: p.book_publisher or ""),
            "description": (use_description, lambda p: p.description_sale or ""),
            "year": (use_year, lambda p: float(p.book_year or 0)),
            "pages": (use_pages, lambda p: float(p.book_pages or 0)),
            "price": (use_price, lambda p: float(p.list_price or 0)),
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

        engine = ItemRecommendationEngine()
        engine.train(df)
        engine.save_model(_ITEM_MODEL_PATH)

        _logger.info("Item model trained: %d products.", len(products))
        return True

    @api.model
    def _load_item_model(self):
        try:
            return ItemRecommendationEngine.load_model(_ITEM_MODEL_PATH)
        except Exception as exc:
            _logger.error("Failed to load item model: %s", exc)
            return None

    @api.model
    def get_similar_products(
        self,
        product_tmpl_id,
        limit=6,
    ):
        engine = self._load_item_model()

        if engine is None:
            return self.env["product.template"]

        product = self.env["product.template"].sudo().browse(product_tmpl_id)

        product_df = pd.DataFrame(
            [
                {
                    "id": product.id,
                    "parent_genre": product.book_genre_id.parent_id.name or "",
                    "genre": str(product.book_genre_id.id or ""),
                    "sub_genre": str(product.book_sub_genre_id.id or ""),
                    "author": product.book_author or "",
                    "publisher": product.book_publisher or "",
                    "description": product.description_sale or "",
                    "year": float(product.book_year or 0),
                    "pages": float(product.book_pages or 0),
                    "price": float(product.list_price or 0),
                }
            ]
        )

        scores = engine.predict(product_df, limit=limit)

        if scores is None:
            return self.env["product.template"]

        return (
            self.env["product.template"]
            .browse(scores.index.tolist())
            .filtered(lambda p: p.website_published)[:limit]
        )
