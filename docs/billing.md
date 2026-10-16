# Stripe Billing

O checkout utiliza as variáveis STRIPE_SECRET_KEY e STRIPE_PRICE_ID_BASE. Os webhooks são verificados por STRIPE_WEBHOOK_SECRET.

## Configuração

1. Criar um produto e um preço mensal no Stripe em modo de teste.
2. Colocar o ID real do preço em STRIPE_PRICE_ID_BASE.
3. Configurar STRIPE_SECRET_KEY de teste e o endpoint de webhook.
4. Configurar o segredo do webhook em STRIPE_WEBHOOK_SECRET.
5. Testar checkout, checkout.session.completed, eventos de subscrição, invoice.paid e invoice.payment_failed.
6. Repetir com credenciais live apenas após revisão do produto e requisitos legais de faturação.

O preço de 39 €/mês é conteúdo inicial de referência, não prova de que a cobrança esteja ativa. As subscrições ainda exigem testes completos, revisão de estados e verificação de idempotência sob concorrência antes do lançamento.
