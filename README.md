# PagamentoConforme

SaaS B2B para organizar documentos de subempreiteiros, rever faturas e preparar ficheiros de pagamentos SEPA em empresas portuguesas.

## Funcionalidades desta primeira implementação

- Registo de empresa, confirmação de email e sessão autenticada.
- Gestão de subempreiteiros, NIF, IBAN e notas.
- Links de submissão assinados, revogáveis e com expiração.
- Upload de PDF, PNG e JPEG com validação de tipo real e limite de tamanho.
- Armazenamento privado local em desenvolvimento ou Supabase Storage quando configurado.
- Extração de texto PDF com PyMuPDF, leitura assistida de QR em faturas e sugestões de campos; os resultados não são tratados como validação oficial.
- Revisão e aprovação humana de faturas.
- Geração de rascunho XML SEPA, com validação local básica.
- Checkout de subscrição Stripe opcional e tratamento inicial de webhooks.
- Auditoria de ações relevantes.
- Migrações Alembic e testes unitários.

## Executar localmente

1. Instalar Python 3.11 ou superior.
2. Criar e ativar um ambiente virtual.
3. Instalar dependências: pip install -r requirements.txt
4. Copiar .env.example para .env.
5. Executar uvicorn app.main:app --reload
6. Abrir http://127.0.0.1:8000.

No modo local, a ligação de confirmação de email aparece nos logs do terminal.

## Testes

Executar pytest.

## Produção

Configurar PostgreSQL, SECRET_KEY, Supabase Storage privado, email de verificação, Stripe e domínio antes de receber documentos reais. O deploy está preparado através de Dockerfile e render.yaml, mas não é considerado operacional até executar os testes de ponta a ponta num ambiente com as integrações configuradas.

## Guardrails

- Não executa transferências bancárias.
- Não pede credenciais de homebanking.
- Não declara verificação oficial da AT ou Segurança Social.
- Não confunde checksum de NIF/IBAN com prova de existência, titularidade ou situação legal.
- Não substitui revisão humana, aconselhamento jurídico ou fiscal.

Consultar a pasta docs para arquitetura, segurança, deploy, subscrições, documentos, exportação e limitações atuais.
