# Segurança — estado inicial

## Medidas existentes no código

- Palavras-passe com hash através de Argon2, usando pwdlib.
- Cookies de sessão assinados, SameSite=Lax, HttpOnly e configuração HTTPS em produção.
- Tokens de submissão assinados, com validade, hash armazenado e revogação.
- Tokens CSRF nos formulários de alteração.
- Verificação de pertença da empresa em consultas de documentos, fornecedores, faturas e lotes.
- Uploads limitados por tamanho e verificação de magic bytes para PDF, PNG e JPEG.
- Nomes de ficheiro higienizados e chaves aleatórias de armazenamento.
- Headers defensivos e respostas sem cache para páginas privadas.
- Chaves Supabase mantidas no servidor.
- Verificação da assinatura de webhook Stripe.
- Registos de auditoria para eventos relevantes.

## Antes de produção

1. Configurar uma chave SECRET_KEY aleatória e privada.
2. Configurar PostgreSQL e executar as migrações.
3. Criar um bucket privado no Supabase Storage e configurar as credenciais do servidor.
4. Configurar email de verificação e validar os fluxos de entrega.
5. Ativar HTTPS e confirmar SESSION_HTTPS_ONLY=true.
6. Executar revisão de segurança independente, incluindo autorização multiempresa, CSRF, tratamento de ficheiros, recuperação de palavra-passe, webhooks e concorrência.
7. Implementar rate limiting distribuído, proteção contra abuso, monitorização e política de resposta a incidentes.
8. Definir conservação, eliminação, backups e recuperação testada.
9. Rever os documentos legais e contratos com subcontratantes de tratamento de dados.

## Aviso

O código atual não constitui certificação de conformidade com o RGPD ou auditoria de segurança. Não carregar documentos fiscais reais até estarem configurados e testados o armazenamento privado e o ambiente de produção.
