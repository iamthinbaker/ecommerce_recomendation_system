/** @odoo-module */

function buildProductCard(p) {
    return `
        <div class="col">
            <a href="${p.url}" class="text-decoration-none text-dark">
                <div class="card h-100 border-0 shadow-sm">
                    <img src="${p.image_url}" class="card-img-top"
                         alt="${p.name}" style="height:160px;object-fit:cover;">
                    <div class="card-body p-2">
                        <p class="card-title small fw-bold mb-1 lh-sm">${p.name}</p>
                        <p class="card-text small text-muted mb-1">${p.author}</p>
                        <p class="card-text small text-primary fw-bold">€${p.price.toFixed(2)}</p>
                    </div>
                </div>
            </a>
        </div>`;
}

function fetchRecommendations(url, gridId) {
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params: {} }),
    })
        .then((r) => r.json())
        .then((data) => {
            const grid = document.getElementById(gridId);
            if (!grid) return;
            const products = data.result || [];
            if (products.length === 0) {
                grid.innerHTML = '';
                grid.closest('section').style.display = 'none';
                return;
            }
            grid.innerHTML = products.map(buildProductCard).join('');
        })
        .catch(() => {
            const grid = document.getElementById(gridId);
            if (grid) grid.closest('section').style.display = 'none';
        });
}

// Product page — item-based recommendations
const productSection = document.getElementById('bookstore_similar_products');
if (productSection) {
    const productId = parseInt(productSection.dataset.productId, 10);
    fetchRecommendations(
        `/bookstore/recommendations/similar/${productId}`,
        'bookstore_similar_products_grid',
    );
}

// Cart — user-based recommendations
const cartSection = document.getElementById('bookstore_cart_user_recommendations');
if (cartSection) {
    const orderId = parseInt(cartSection.dataset.orderId, 10);
    fetchRecommendations(
        `/bookstore/recommendations/user/${orderId}`,
        'bookstore_cart_user_recs_grid',
    );
}

// Order confirmation — user-based recommendations
const confSection = document.getElementById('bookstore_user_recommendations');
if (confSection) {
    const orderId = parseInt(confSection.dataset.orderId, 10);
    fetchRecommendations(
        `/bookstore/recommendations/user/${orderId}`,
        'bookstore_user_recs_grid',
    );
}
