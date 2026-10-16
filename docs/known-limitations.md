# Limitações conhecidas do MVP

- O armazenamento local existe apenas para desenvolvimento. Em produção, uploads exigem Supabase Storage configurado.
- A aplicação usa autenticação própria com sessões assinadas; a configuração multiempresa e o fluxo de autenticação devem ser revistos antes de clientes reais.
- A recuperação de palavra-passe usa ligação assinada e email; é necessária validação de ponta a ponta com o fornecedor de email em produção.
- A gestão completa de convites de equipa e delegação administrativa ainda não está implementada na interface.
- Ainda não existe rate limiting distribuído dedicado em todos os endpoints públicos.
- A leitura de texto e QR não valida autenticidade oficial nem consulta AT/Segurança Social.
- Imagens são aceites e o leitor de QR tenta descodificá-las, mas ainda não existe OCR completo para texto de imagens digitalizadas.
- A importação CSV tem pré-visualização e validação básica por linha; falta uma suite dedicada de testes de abuso, grandes ficheiros e concorrência.
- Não existe validação XML completa contra XSD de banco nem teste de aceitação em bancos portugueses.
- Stripe necessita de credenciais reais em modo de teste, configuração de produto/preço e testes completos de ponta a ponta.
- As tarefas programadas de avisos documentais e emails recorrentes ainda não estão implementadas como worker robusto.
- A política legal e os contratos de tratamento de dados carecem de revisão profissional.
- O produto não está considerado pronto para produção até existir deploy, configuração externa, revisão de segurança e testes end-to-end documentados.
