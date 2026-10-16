# Arquitetura

## Componentes

- Shopify: site público e informação comercial. Não processa documentos.
- FastAPI: interface autenticada, lógica da aplicação, uploads, revisão e preparação de lotes.
- PostgreSQL: utilizadores, empresas, permissões, fornecedores, documentos, faturas, lotes e auditoria.
- Supabase Storage: armazenamento privado quando as variáveis de ambiente estão configuradas.
- Stripe: subscrições quando as credenciais e o ID de preço estão configurados.
- Resend: email de verificação quando a chave e o remetente estão configurados.

## Fluxo principal

1. Uma empresa cria conta e confirma o email.
2. Adiciona subempreiteiros e regista os IBANs.
3. Gera um link assinado, revogável e com validade para cada fornecedor.
4. O fornecedor carrega a fatura e os documentos.
5. O servidor valida o tipo real do ficheiro, guarda-o em armazenamento privado e tenta extrair texto dos PDFs.
6. A empresa revê as sugestões e validações.
7. Um utilizador autorizado aprova explicitamente cada fatura.
8. A aplicação prepara um XML SEPA para revisão e carregamento manual no banco.

## Limites atuais

Esta é a primeira implementação do MVP. O leitor de documentos é auxiliar; não existe verificação oficial junto da AT ou Segurança Social. A validação XML local não substitui o XSD bancário. O OCR para imagens, importação CSV, recuperação de palavra-passe, convites de utilizadores e políticas de rate limiting dedicadas são trabalho pendente. A camada de autenticação da aplicação é própria e deve passar revisão de segurança antes de uso comercial.
