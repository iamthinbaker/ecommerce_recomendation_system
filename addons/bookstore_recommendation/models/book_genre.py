from odoo import fields, models


class BookGenre(models.Model):
    _name = 'book.genre'
    _description = 'Book Genre'
    _order = 'sequence, name'

    name = fields.Char(string='Genre', required=True, translate=True)
    description = fields.Text(string='Description', translate=True)
    website_published = fields.Boolean(string='Published on Website', default=True)
    sequence = fields.Integer(default=10)

    parent_id = fields.Many2one(
        comodel_name='book.genre',
        string='Parent Genre',
        ondelete='set null',
        index=True,
    )
    child_ids = fields.One2many(
        comodel_name='book.genre',
        inverse_name='parent_id',
        string='Sub-genres',
    )

    # Public eCommerce category linked to this genre (for /shop?category= filtering)
    public_categ_id = fields.Many2one(
        comodel_name='product.public.category',
        string='Shop Category',
        ondelete='set null',
    )

    product_count = fields.Integer(
        string='Books',
        compute='_compute_product_count',
    )

    def _compute_product_count(self):
        for genre in self:
            # Count books in this genre AND all its children (non-disjoint sections)
            all_ids = [genre.id] + genre.child_ids.ids
            genre.product_count = self.env['product.template'].search_count(
                [('book_genre_id', 'in', all_ids)]
            )

    def _get_all_child_ids(self):
        """Return this genre's id plus all descendant ids."""
        ids = list(self.ids)
        for child in self.child_ids:
            ids += child._get_all_child_ids()
        return ids
