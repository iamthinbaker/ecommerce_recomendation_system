import logging
import os
import pickle

import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity

from odoo import api, models

_logger = logging.getLogger(__name__)

_MODELS_DIR = os.path.join(os.path.dirname(__file__), '..', 'static', 'models')
_USER_MODEL_PATH = os.path.join(_MODELS_DIR, 'user_svd.pkl')


class UserRecommendationEngine(models.AbstractModel):
    _name = 'recommendation.engine.user'
    _inherit = 'recommendation.engine.base'
    _description = 'User-Based Recommendation Engine'

    @api.model
    def _train_user_model(self, months=None, min_user_orders=1):
        matrix = self._build_user_item_matrix(months=months, min_user_orders=min_user_orders)
        if matrix is None or matrix.shape[0] < 5:
            _logger.warning('Not enough users to train user model.')
            return False

        n_components = min(50, matrix.shape[0] - 1, matrix.shape[1] - 1)
        svd = TruncatedSVD(n_components=n_components, random_state=42)
        user_factors = pd.DataFrame(
            svd.fit_transform(matrix.values),
            index=matrix.index,
        )

        os.makedirs(_MODELS_DIR, exist_ok=True)
        with open(_USER_MODEL_PATH, 'wb') as f:
            pickle.dump({
                'svd': svd,
                'user_factors': user_factors,
                'matrix': matrix,
            }, f)

        _logger.info(
            'User model trained: %d users, %d products.',
            matrix.shape[0], matrix.shape[1],
        )
        return True

    @api.model
    def _load_user_model(self):
        if not os.path.exists(_USER_MODEL_PATH):
            return None
        try:
            with open(_USER_MODEL_PATH, 'rb') as f:
                return pickle.load(f)
        except Exception as exc:
            _logger.error('Failed to load user model: %s', exc)
            return None

    @api.model
    def get_user_recommendations(self, partner_id, limit=6):
        model = self._load_user_model()
        if model is None:
            return self.env['product.template']

        user_factors = model['user_factors']
        matrix = model['matrix']

        if partner_id not in user_factors.index:
            return self._get_popular_products(limit=limit)

        user_vec = user_factors.loc[[partner_id]].values
        sims = pd.Series(
            cosine_similarity(user_vec, user_factors.values)[0],
            index=user_factors.index,
        )
        sims[partner_id] = -1

        top_neighbors = sims.nlargest(20)
        top_neighbors = top_neighbors[top_neighbors > 0]

        already_bought = matrix.columns[matrix.loc[partner_id] > 0]

        scores = pd.Series(0.0, index=matrix.columns)
        for neighbor_id, weight in top_neighbors.items():
            scores += weight * matrix.loc[neighbor_id]
        scores[already_bought] = 0

        recommended_ids = scores.nlargest(limit).index.tolist()

        return self.env['product.template'].browse(recommended_ids).filtered(
            lambda p: p.website_published
        )

    @api.model
    def _get_popular_products(self, limit=6):
        self.env.cr.execute("""
            SELECT pt.id, SUM(sol.product_uom_qty) AS total
            FROM sale_order_line sol
            JOIN product_product pp ON pp.id = sol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN sale_order so ON so.id = sol.order_id
            WHERE so.state IN ('sale', 'done')
            GROUP BY pt.id
            ORDER BY total DESC
            LIMIT %s
        """, (limit,))
        ids = [r[0] for r in self.env.cr.fetchall()]
        return self.env['product.template'].browse(ids).filtered(
            lambda p: p.website_published
        )
