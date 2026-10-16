# Exportação SEPA

O gerador produz um rascunho XML com namespace pain.001.001.03 a partir de faturas aprovadas e IBANs que passam o checksum. O ficheiro fica associado a um lote e pode ser descarregado por um utilizador autenticado da empresa.

## Limitações

A validação implementada é local e básica; não é uma validação completa contra XSD nem confirmação de aceitação por um banco. Os dados do agente bancário e os perfis de execução podem exigir campos adicionais. O formato e perfil suportados devem ser confirmados para cada banco antes de se utilizar um ficheiro em operações reais.

O PagamentoConforme não executa transferências nem pede credenciais bancárias. O utilizador revê o XML e carrega-o manualmente no banco.
