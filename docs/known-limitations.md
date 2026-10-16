# Limitações conhecidas do MVP

- O armazenamento local existe apenas para desenvolvimento. Em produção, uploads exigem Supabase Storage configurado.
- A aplicação usa autenticação própria com sessões assinadas; a configuração multiempresa e o fluxo de autenticação devem ser revistos antes de clientes reais.
- A confirmação de email depende de Resend em produção.
- Não há recuperação de palavra-passe implementada.
- Não há gestão de convites e múltiplos utilizadores completa na interface.
- Ainda não existe rate limiting dedicado em todos os endpoints públicos.
- A leitura de documentos não valida autenticidade oficial nem consulta AT/Segurança Social.
- Imagens são aceites e guardadas, mas ainda não são processadas por OCR.
- A importação CSV de fornecedores ainda não está implementada.
- Não existe verificação completa de XML contra XSD bancário ou teste de aceitação de bancos.
- Stripe necessita de credenciais reais em modo de teste, configuração de produto/preço e testes de ponta a ponta.
- A política legal e os contratos de tratamento de dados carecem de revisão profissional.
