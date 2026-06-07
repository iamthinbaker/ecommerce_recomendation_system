import logging
import os

import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

from odoo import api, models

_logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "models")
_ITEM_MODEL_PATH = os.path.join(_MODELS_DIR, "item_similarity.json")


class ItemRecommendationEngine(models.AbstractModel):
    _name = "recommendation.engine.item"
    _inherit = "recommendation.engine.base"
    _description = "Item-Based Recommendation Engine"

    @api.model
    def _train_item_model(self, months=None, min_product_orders=1):
        products = self.env["product.template"].sudo().search([("is_book", "=", True)])

        if len(products) < 2:
            _logger.warning("Not enough products to train item model.")
            return False

        features = (
            pd.DataFrame(
                [
                    {
                        "id": p.id,
                        "genre": str(p.book_genre_id.id or ""),
                        "sub_genre": str(p.book_sub_genre_id.id or ""),
                        "author": p.book_author or "",
                        "publisher": p.book_publisher or "",
                        "year": float(p.book_year or 0),
                        "pages": float(p.book_pages or 0),
                    }
                    for p in products
                ]
            )
            .set_index("id")
            .pipe(
                lambda df: pd.concat(
                    [
                        pd.get_dummies(
                            df[
                                [
                                    "genre",
                                    "sub_genre",
                                    "author",
                                    "publisher",
                                ]
                            ]
                        ),
                        pd.DataFrame(
                            MinMaxScaler().fit_transform(
                                df[
                                    [
                                        "year",
                                        "pages",
                                    ]
                                ]
                            ),
                            columns=["year", "pages"],
                            index=df.index,
                        ),
                    ],
                    axis=1,
                )
            )
        )

        similarity_df = pd.DataFrame(
            cosine_similarity(features.values),
            index=features.index,
            columns=features.index,
        )

        os.makedirs(_MODELS_DIR, exist_ok=True)
        similarity_df.to_json(
            _ITEM_MODEL_PATH,
            orient="records",
            indent=4,
        )

        _logger.info("Item model trained: %d products.", len(products))
        return True

    @api.model
    def _load_item_model(self):
        try:
            df = pd.read_json(_ITEM_MODEL_PATH, orient="records")
            df.index = df.index.astype(int)
            df.columns = df.columns.astype(int)
            return df
        except Exception as exc:
            _logger.error("Failed to load item model: %s", exc)
            return None

    @api.model
    def get_similar_products(
        self,
        product_tmpl_id,
        limit=6,
    ):
        similarity_df = self._load_item_model()
        if similarity_df is None or product_tmpl_id not in similarity_df.index:
            return self.env["product.template"]

        scores = (
            (
                # Get similarity scores for the given product template, excluding itself
                similarity_df[product_tmpl_id]
                .drop(product_tmpl_id)
                .nlargest(limit * 3)
                .to_frame("similarity")
                # Add product template records to apply additional filters and boosts
                # .assign(
                #     product_card=lambda df: self.env["product.template"].browse(
                #         df.index.tolist()
                #     )
                # )
                # # Boost similarity for promoted books
                # .assign(
                #     similarity=lambda df: df.similarity
                #     + df.product_card.apply(lambda p: p.book_promoted) * 0.3
                # )
            )
            .sort_values(
                "similarity",
                ascending=False,
            )
            .head(limit)
        )

        return (
            self.env["product.template"]
            .browse(scores.index.tolist())
            .filtered(lambda p: p.website_published)[:limit]
        )
