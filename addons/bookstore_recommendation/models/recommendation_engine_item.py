import logging
import os
import pickle

import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

from odoo import api, models

_logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'models')
_ITEM_MODEL_PATH = os.path.join(_MODELS_DIR, 'item_similarity.pkl')


class ItemRecommendationEngine(models.AbstractModel):
    _name = 'recommendation.engine.item'
    _inherit = 'recommendation.engine.base'
    _description = 'Item-Based Recommendation Engine'

    @api.model
    def _train_item_model(self, months=None, min_product_orders=1):
        matrix = self._build_user_item_matrix(months=months, min_product_orders=min_product_orders)
        if matrix is None or matrix.shape[1] < 2:
            _logger.warning('Not enough purchase data to train item model.')
            return False

        similarity = cosine_similarity(matrix.T.values)
        similarity_df = pd.DataFrame(
            similarity,
            index=matrix.columns,
            columns=matrix.columns,
        )

        os.makedirs(_MODELS_DIR, exist_ok=True)
        with open(_ITEM_MODEL_PATH, 'wb') as f:
            pickle.dump({'similarity': similarity_df}, f)

        _logger.info('Item model trained: %d products.', len(matrix.columns))
        return True

    @api.model
    def _load_item_model(self):
        if not os.path.exists(_ITEM_MODEL_PATH):
            return None
        try:
            with open(_ITEM_MODEL_PATH, 'rb') as f:
                return pickle.load(f)
        except Exception as exc:
            _logger.error('Failed to load item model: %s', exc)
            return None

    @api.model
    def get_similar_products(self, product_tmpl_id, limit=6):
        model = self._load_item_model()
        if model is None:
            return self.env['product.template']

        similarity_df = model['similarity']
        if product_tmpl_id not in similarity_df.index:
            return self.env['product.template']

        similar_ids = (
            similarity_df[product_tmpl_id]
            .drop(product_tmpl_id)
            .nlargest(limit * 3)
            .index.tolist()
        )

        return self.env['product.template'].browse(similar_ids).filtered(
            lambda p: p.website_published
        )[:limit]
