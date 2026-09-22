# HANDOFF / DUMP DE CONTEXTO — SEI COLABORAGOV

## Objetivo

Criar um cliente/coletor em Python para consultar processos do SEI/ColaboraGov e baixar os documentos públicos associados a eles, com foco posterior em extração/análise de informações relevantes.

Instância:
https://colaboragov.sei.gov.br/

Página inicialmente fornecida pelo usuário:
https://colaboragov.sei.gov.br/sei/controlador_externo.php?acao=usuario_externo_logar&id_orgao_acesso_externo=7

Esclarecimento: essa URL é de acesso para usuário externo e não é a página adequada para consulta pública. O fluxo usa o módulo de Pesquisa Pública.

---

## 1. Necessidade

O usuário quer informar uma lista de números de processos SEI, por exemplo:

21260.003436/2026-15

e automatizar:

1. consultar os processos na Pesquisa Pública do ColaboraGov;
2. identificar o processo;
3. abrir a página pública;
4. enumerar documentos públicos;
5. baixar os arquivos públicos;
6. respeitar rate-limit;
7. retomar após falhas/interrupção;
8. persistir estado localmente;
9. posteriormente extrair texto;
10. futuramente usar busca semântica/LLM/RAG.

O escopo é informação pública; não acessar documentos restritos.

---

## 2. Pesquisa Pública do SEI

O SEI possui o módulo oficial de Pesquisa Pública. Repositório:
https://github.com/anatelgovbr/mod-sei-pesquisa

O módulo possui página de pesquisa, controller AJAX externo, paginação, páginas públicas de processos e documentos, e links públicos assinados/criptografados.

A Pesquisa Pública só disponibiliza aquilo que o órgão tornou público.

---

## 3. Endpoint AJAX descoberto pelo usuário

O usuário capturou no DevTools a requisição após clicar em “Pesquisar”:

https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_controlador_ajax_externo.php?acao_ajax_externo=protocolo_pesquisar&id_orgao_acesso_externo=7&isPaginacao=false&inicio=0&rowsSolr=50

Parâmetros gerais conhecidos:
- acao_ajax_externo=protocolo_pesquisar
- id_orgao_acesso_externo=7
- isPaginacao=false
- inicio=0
- rowsSolr=50

O módulo usa páginas de 50 resultados.

Esse endpoint é um endpoint AJAX real do módulo SEI Pesquisa Pública e pode devolver JSON. Porém não deve ser tratado automaticamente como uma API REST pública, estável e documentada.

É um controller AJAX da aplicação web e pode depender de:
- sessão;
- cookies;
- payload/form data;
- tokens/validação;
- CAPTCHA.

---

## 4. Exemplo de busca capturado pelo usuário

Pesquisa em:
- Processos
- Documentos Gerados
- Documentos Externos

Órgão gerador:
- MMulheres

Unidade Geradora:
- MMULHERES-SE-SGA-CGATI-CTI-DTI

Data:
- 14/09/2026 até 22/09/2026

O endpoint AJAX pode ser útil não somente para consulta individual por número, mas também para descoberta por órgão/unidade/período.

---

## 5. Web Service oficial do SEI

Existe Web Service oficial do SEI, tradicionalmente SOAP/XML, com operações como:
- consultarProcedimento
- consultarDocumento
- listarUnidades
- listarAndamentos
- etc.

Endpoint tradicional:
`/sei/ws/SeiWS.php`

Esse Web Service NÃO é uma API pública anônima. Normalmente exige:
- configuração do órgão;
- sistema consumidor cadastrado;
- identificação/credencial;
- permissões;
- eventualmente controles de origem/IP.

A operação consultarProcedimento existe e consulta processos de forma estruturada.

---

## 6. REST / mod-wssei

Existe:
https://github.com/pengovbr/mod-wssei

Esse módulo adiciona REST/JSON ao SEI.

Seria melhor para integração, caso o ColaboraGov tenha o módulo instalado e exista autorização para seu uso.

Ainda NÃO foi confirmado nesta conversa que o ColaboraGov exponha publicamente o WSSEI.

---

## 7. Conclusão sobre “API pública”

Resposta consolidada:

- Existe um endpoint JSON/AJAX real da Pesquisa Pública: `md_pesq_controlador_ajax_externo.php`.
- Ele é a coisa mais próxima de uma “API pública” no contexto da Pesquisa Pública.
- Não é uma API REST pública documentada no sentido tradicional.
- Existe Web Service oficial SOAP (`SeiWS.php`), mas é destinado a integração autorizada.
- Existe REST (`mod-wssei`), mas sua disponibilidade depende da instalação/configuração do órgão.

Prioridade atual: investigar o endpoint AJAX diretamente e descobrir se pode ser consumido por Python sem depender da automação completa da página.

---

## 8. CAPTCHA

A Pesquisa Pública pode apresentar CAPTCHA.

Regra:
- NÃO resolver/burlar automaticamente;
- usuário resolve manualmente no navegador;
- automatizar somente o restante do fluxo.

Problemas encontrados:

### Problema 1
O código antigo verificava apenas se `.retorno-ajax` estava visível e esperava Enter no terminal.

O usuário relatou:
“estou preenchendo o valor do captcha no campo de texto e aperto o Enter no terminal e a execução não volta nunca”.

Correção proposta:
- não usar `input()`/Enter;
- detectar quando `#txtInfraCaptcha` recebe valor;
- usuário digita no navegador;
- o programa continua automaticamente.

### Problema 2
Depois:

2026-09-11 14:45:36 | INFO | CAPTCHA preenchido.
2026-09-11 14:45:36 | INFO | Executando a pesquisa...
2026-09-11 14:47:07 | INFO | Diagnóstico salvo: .state\debug
...
Timeout 90000ms
...
RuntimeError: A Pesquisa Pública não apresentou resultado dentro do prazo.

Diagnóstico: o código tentou esperar a resposta AJAX depois do submit, podendo perder a sincronização; além disso, era melhor deixar o fluxo de submit do formulário real do SEI ocorrer.

Foi proposta a arquitetura:
- instalar `expect_response` antes do submit;
- usar o formulário real `#seiSearch`;
- usar `requestSubmit()`;
- observar uma resposta POST contendo `isPaginacao=true`;
- analisar o JSON;
- depois verificar o DOM.

Essa última tentativa NÃO foi confirmada como funcional pelo usuário.

---

## 9. Fluxo Javascript oficial relevante

Arquivo:
https://github.com/anatelgovbr/mod-sei-pesquisa/blob/master/sei/web/modulos/pesquisa/md_pesq_processo_pesquisar_js.php

Fluxo identificado:

1. `OnSubmitForm()`
2. `CaptchaSEI::validarOnSubmit('seiSearch')`
3. quando `captchaValidado == '3'`
4. chama `carregarProximaPagina()`
5. `carregarProximaPagina()` faz `$.post(...)`
6. usa:
   - `isPaginacao=true`
   - `inicio`
   - `rowsSolr`
   - `$('#seiSearch').serialize()`
7. recebe resposta com campos como:
   - `itens`
   - `html`
8. insere HTML dentro de `.retorno-ajax > table > tbody`
9. `updateCaptcha()` pode limpar/atualizar o CAPTCHA após a requisição.

Isso explica por que verificar apenas “captcha ainda está visível?” é incorreto: o campo pode estar visível mesmo quando o CAPTCHA já foi enviado/validado, e o próprio `updateCaptcha()` pode limpar o input depois.

---

## 10. Primeiro erro de Playwright

Erro:
`Page.wait_for_selector: Timeout 30000ms exceeded`

Mensagem:
`locator(".retorno-ajax") resolved to hidden <div id="conteudo" class="retorno-ajax">…</div>`

Diagnóstico:
`.retorno-ajax` já existe no DOM, mas pode estar oculto.

Conclusão:
não esperar por `.retorno-ajax` ficar VISÍVEL.

Esperar por conteúdo interno, por exemplo:
- `.retorno-ajax table tbody tr`
- `.retorno-ajax .sem-resultado`
- ou link `a[href*="md_pesq_processo_exibir.php"]`

---

## 11. Projeto Python inicialmente criado

Estrutura:

sei-colaboragov/
├── main.py
├── requirements.txt
├── processos.txt
├── README.md
├── .gitignore
└── downloads/

Um `main.py` grande foi criado contendo:
- rate limiter;
- SQLite;
- Playwright;
- pesquisa;
- extração de documentos;
- download;
- metadata;
- CLI;
- diagnóstico.

Arquitetura:
lista de processos
→ Pesquisa Pública
→ processo
→ documentos públicos
→ download
→ SQLite/metadata

---

## 12. Dependências

requirements.txt inicialmente:
playwright>=1.52,<2
beautifulsoup4>=4.13,<5
lxml>=5.3,<6
requests>=2.32,<3

Erro no ambiente do usuário:
- Windows
- Python 3.14 (`cp314`)
- pip tentou instalar `lxml 5.4.0` via source
- compilação falhou com:
  `fatal error C1083: Cannot open include file: 'libxml/xmlversion.h'`

Correção recomendada:
REMOVER `lxml`, pois não é necessário.

requirements.txt atual:
playwright>=1.52,<2
beautifulsoup4>=4.13,<5

Usar:
`BeautifulSoup(html, "html.parser")`

Não usar:
`BeautifulSoup(html, "lxml")`

---

## 13. Rate limit

Não foi estabelecido um limite público universal do ColaboraGov.

Foi adotado inicialmente:
- mínimo: 2 segundos
- máximo: 5 segundos

com intervalo aleatório.

Tratamento:
- 429 → respeitar `Retry-After`, quando presente;
- 5xx → exponential backoff;
- erros de conexão → retry;
- processamento sequencial, sem paralelismo.

CLI:
`python main.py --min-delay 3 --max-delay 7`

---

## 14. SQLite

Objetivo: retomar sem perder progresso.

Tabela `processes`:
- id
- requested_number
- normalized_number
- status
- title
- process_url
- error
- created_at
- updated_at

Tabela `documents`:
- id
- process_id
- document_number
- name
- url
- status
- local_path
- sha256
- content_type
- error
- created_at
- updated_at

Estados:
- pending
- searching
- found
- downloading
- downloaded
- retry
- not_found
- completed

---

## 15. Arquivos baixados

Estrutura pretendida:

downloads/
└── 21260.003436_2026-15/
    ├── metadata.json
    ├── 1234567_Nota_Tecnica.pdf
    ├── 1234568_Despacho.pdf
    └── ...

metadata.json:
- número do processo
- URL pública
- título
- data de coleta
- documentos
- URL pública de cada documento
- status
- arquivo local
- SHA-256
- Content-Type
- erro

---

## 16. Links de processo/documento

O módulo gera links:
- `md_pesq_processo_exibir.php`
- `md_pesq_documento_consulta_externa.php`

Foi decidido não fabricar parâmetros criptografados/assinados.

Estratégia:
- obter o link fornecido pela própria Pesquisa Pública;
- seguir exatamente esse link.

---

## 17. Download

Versão posterior passou a usar:
`context.request.get(...)`

em vez de `requests.Session()`.

Objetivo:
- reutilizar a mesma sessão/cookies do navegador;
- evitar copiar cookies manualmente;
- manter contexto autenticado/externo quando necessário.

Tratamentos:
- detectar HTML retornado no lugar do arquivo;
- rejeitar conteúdo vazio;
- salvar primeiro em `.part`;
- renomear ao final;
- calcular SHA-256;
- determinar extensão por Content-Type;
- evitar colisão de nomes.

---

## 18. Input de processos

Arquivo:
`processos.txt`

Exemplo:

# Um processo por linha.

21260.003436/2026-15
21260.003437/2026-16
21260.003438/2026-17

Linhas vazias e linhas iniciadas por `#` são ignoradas.

---

## 19. Melhor estratégia atual

Não continuar aumentando a complexidade do Playwright até entender o endpoint AJAX.

A prioridade agora é reproduzir exatamente o request do navegador:

DevTools
→ Network
→ `md_pesq_controlador_ajax_externo.php`
→ Copy
→ Copy as cURL

Precisamos obter:
- método HTTP;
- URL;
- query params;
- Request Payload / Form Data;
- headers relevantes;
- cookies necessários;
- token/campo relacionado ao CAPTCHA;
- JSON exato de resposta.

A partir disso, montar um cliente Python HTTP fiel.

---

## 20. Requisição conhecida

URL:
https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_controlador_ajax_externo.php?acao_ajax_externo=protocolo_pesquisar&id_orgao_acesso_externo=7&isPaginacao=false&inicio=0&rowsSolr=50

Conhecidos:
- `acao_ajax_externo=protocolo_pesquisar`
- `id_orgao_acesso_externo=7`
- `isPaginacao=false`
- `inicio=0`
- `rowsSolr=50`

AINDA NÃO consolidado:
- payload completo;
- headers completos;
- cookies;
- token/campo CAPTCHA;
- JSON exato retornado pela instância do ColaboraGov;
- se o endpoint funciona fora do navegador sem sessão específica.

Não presumir esses dados.

---

## 21. Objetivo futuro

Ideal:

SEI ColaboraGov
→ endpoint de pesquisa/JSON
→ lista de processos
→ metadados
→ documentos públicos
→ download
→ extração de texto
→ indexação
→ busca lexical + embeddings
→ RAG/LLM

Consulta futura exemplo:
“Encontre nos processos públicos da unidade X os contratos relacionados a Y e extraia valores, vigência, aditivos e pagamentos.”

---

## 22. Próximo passo mais útil

O usuário deve fornecer o “Copy as cURL” da requisição real observada no DevTools.

Com ele:
1. reproduzir a chamada em Python;
2. identificar o JSON real;
3. descobrir quais campos do formulário são necessários;
4. verificar dependência de cookie/sessão/CAPTCHA;
5. eliminar Playwright para a parte que puder ser feita diretamente por HTTP;
6. manter rate-limit;
7. depois implementar consulta por número, órgão, unidade e período;
8. depois implementar download de documentos públicos.

---

## 23. Fontes técnicas usadas na investigação

Módulo SEI Pesquisa Pública:
https://github.com/anatelgovbr/mod-sei-pesquisa

Javascript principal:
https://github.com/anatelgovbr/mod-sei-pesquisa/blob/master/sei/web/modulos/pesquisa/md_pesq_processo_pesquisar_js.php

REST WSSEI:
https://github.com/pengovbr/mod-wssei

Endpoint AJAX real:
https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_controlador_ajax_externo.php?acao_ajax_externo=protocolo_pesquisar&id_orgao_acesso_externo=7&isPaginacao=false&inicio=0&rowsSolr=50

Página pública:
https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=7

---

# PROMPT DE CONTINUIDADE PARA OUTRO CHAT

“Estou continuando um projeto de integração com a Pesquisa Pública do SEI/ColaboraGov. A instância é https://colaboragov.sei.gov.br/ e o endpoint AJAX real capturado pelo navegador é:

https://colaboragov.sei.gov.br/sei/modulos/pesquisa/md_pesq_controlador_ajax_externo.php?acao_ajax_externo=protocolo_pesquisar&id_orgao_acesso_externo=7&isPaginacao=false&inicio=0&rowsSolr=50

O objetivo é consultar processos e documentos públicos em Python, respeitando rate-limit, persistindo estado, retomando falhas e baixando documentos públicos. Não quero contornar CAPTCHA nem acessar documentos restritos.

O módulo oficial é:
https://github.com/anatelgovbr/mod-sei-pesquisa

O Javascript relevante é:
https://github.com/anatelgovbr/mod-sei-pesquisa/blob/master/sei/web/modulos/pesquisa/md_pesq_processo_pesquisar_js.php

Ele usa `OnSubmitForm()`, validação de CAPTCHA, `carregarProximaPagina()`, `$.post(...)`, `isPaginacao=true`, `inicio`, `rowsSolr`, `$('#seiSearch').serialize()`, e retorna dados como `itens` e `html`.

Já houve problemas com Playwright:
- `.retorno-ajax` é um container que pode existir oculto; não esperar sua visibilidade.
- esperar o resultado AJAX depois do submit pode perder a sincronização.
- o usuário resolve o CAPTCHA manualmente no navegador; o código deve detectar que `#txtInfraCaptcha` foi preenchido sem exigir Enter no terminal.

Também existe Web Service SOAP do SEI (`SeiWS.php`) e o módulo REST `mod-wssei`, mas ainda não foi confirmado que o ColaboraGov exponha uma API REST pública/autorizada.

Agora a prioridade é descobrir/reproduzir diretamente a chamada AJAX do endpoint. Não invente parâmetros. Se eu fornecer um Copy as cURL da requisição, converta-o fielmente para Python e mostre como obter o JSON real.”

