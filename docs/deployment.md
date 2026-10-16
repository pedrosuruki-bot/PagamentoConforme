# Deploy

## Desenvolvimento local

1. Instalar Python 3.11+.
2. Criar ambiente virtual e instalar dependências com pip install -r requirements.txt.
3. Copiar .env.example para .env.
4. Manter APP_ENV=development para usar armazenamento local durante desenvolvimento.
5. Executar uvicorn app.main:app --reload.
6. Abrir http://127.0.0.1:8000.

No modo local, a ligação de verificação do email é registada na consola do servidor.

## Render

O repositório contém Dockerfile e render.yaml. O Blueprint está configurado no plano Free para evitar criar custos automaticamente e deve ser usado apenas para pré-visualização/testes. Os serviços Free podem suspender-se quando estão inativos e o sistema de ficheiros local é efémero; não usar este ambiente para documentos reais nem como produção. Antes de um lançamento comercial, é necessário aprovar um plano pago adequado e configurar os serviços persistentes.

Antes do deploy de teste, configurar DATABASE_URL PostgreSQL, SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY. O bucket private-documents tem de existir como bucket privado. Stripe e email só são necessários para testar essas integrações e também têm de ser configurados com credenciais próprias.

A imagem executa a migração antes de arrancar. Verificar logs, /health, registo, confirmação de email, upload privado, download protegido, aprovação de faturas e validação do XML.

## Domínio

O endereço app.pagamentoconforme.pt é apenas o domínio pretendido. É necessário configurá-lo no fornecedor de alojamento e no DNS da zona do domínio real. Não existe garantia de que esteja registado ou disponível.

## Segurança operacional

Não colocar segredos no GitHub. Não utilizar armazenamento local efémero para documentos. Não declarar o deploy concluído até testar o URL público e os fluxos essenciais. O URL onrender.com só existe depois de criar o serviço no Render; não assumir que já está publicado.
