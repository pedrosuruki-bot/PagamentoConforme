# Validação documental

O sistema permite carregar certidões da AT, Segurança Social, seguros, outros documentos e faturas em PDF, PNG ou JPEG. Extrai texto de PDFs, tenta ler QR das faturas com zxing-cpp e produz sugestões estruturadas dos campos A, B, C, D, E, F, G, H, I*, N, O, Q, R e S quando presentes. As sugestões são armazenadas com o documento para revisão humana.

A leitura de texto não prova autenticidade, validade legal nem situação fiscal oficial. Os estados de documento são auxiliares e carecem de revisão humana.

## Próximos incrementos

- Melhorar a cobertura de testes do leitor de QR contra os exemplos oficiais mais recentes da AT.
- Extração estruturada com proveniência e confiança.
- OCR para imagens e PDFs digitalizados.
- Regras versionadas para tipos documentais e datas de validade.
- Testes com documentos artificiais e fixtures controladas.
- Revisão jurídica das regras e dos textos apresentados ao utilizador.
