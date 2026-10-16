# Operação

- Consultar logs do serviço para erros e ligações de confirmação locais.
- Verificar /health depois de deploy.
- Executar pytest antes de fazer merge.
- Criar backups de PostgreSQL e testar regularmente a recuperação.
- Rever alertas do fornecedor de alojamento e do armazenamento privado.
- Rodar segredos expostos e não reutilizar chaves de teste em produção.
- Rever erros de processamento e limpar órfãos de armazenamento através de uma tarefa de manutenção controlada.
- Testar mensalmente renovação de subscrição e recuperação a partir de backup.


## Alertas de validade

Foi adicionado um worker executável manualmente através de `python scripts/send_document_reminders.py`. O worker verifica documentos com datas de validade registadas, envia emails via Resend e regista cada etapa para evitar duplicações. Os avisos são administrativos e baseiam-se na data registada, não numa verificação oficial.

Para ativar recorrência, configurar um agendador externo diário que execute o script com as variáveis `DATABASE_URL`, `SECRET_KEY`, `RESEND_API_KEY` e `EMAIL_FROM`. O worker ainda não está agendado por defeito nem faz parte de uma implantação Render ativa.
