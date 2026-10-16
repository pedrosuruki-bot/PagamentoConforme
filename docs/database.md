# Base de dados

O SQLAlchemy declara as tabelas iniciais para utilizadores, empresas, memberships, subempreiteiros, links de submissão, documentos, faturas, lotes de pagamento, itens de lote, auditoria, eventos Stripe e subscrições.

As relações carregam company_id para limitar cada consulta ao espaço de trabalho. O backend deve incluir a empresa no filtro de qualquer consulta de documentos, faturas, lotes ou fornecedores.

## Migrações

- alembic.ini contém a configuração local.
- alembic/env.py utiliza DATABASE_URL.
- A primeira revisão cria o esquema inicial.

Em desenvolvimento, a aplicação pode criar tabelas automaticamente. Em produção, o Docker executa a migração antes de iniciar o servidor.

Antes de alterar o esquema em produção, cria uma migração nova, testa-a contra uma cópia da base de dados e prepara um plano de recuperação.
