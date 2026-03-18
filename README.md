# Order Service: Microsserviço de Ordens de Serviço

> Código e docstrings em inglês seguindo convenção técnica universal. README em português por ser o entregável de comunicação do desafio.

Microsserviço backend para registro de ordens de serviço com API HTTP, validação de solicitantes, idempotência, Transactional Outbox Pattern e observabilidade completa.

## Quickstart

```bash
python dev.py help     # lista todos os comandos disponíveis
python dev.py up       # sobe todos os serviços
python dev.py orders   # smoke test contra a API
python dev.py logs     # acompanha eventos em tempo real
python dev.py test     # roda a suite completa de testes
```

---

## dev.py: Task Runner

O projeto inclui um task runner (`dev.py`) que automatiza todas as operações do ciclo de desenvolvimento local, desde subir o ambiente até rodar os testes e inspecionar eventos.

### Por que um task runner em vez de Makefile?

`make` não está disponível por padrão no Windows e exige instalação manual. Como a experiência local precisa funcionar de forma idêntica para qualquer desenvolvedor ou avaliador, independente do sistema operacional, o `dev.py` foi criado usando apenas Python puro, sem dependências externas.

Esse cuidado com o ambiente local reflete uma prática adotada em projetos profissionais: **todo projeto construído do zero precisa ter sua base local documentada e funcional para o time inteiro**, não apenas para quem o criou. Em ambientes cloud-first, isso também significa que o ambiente local deve espelhar fielmente o que vai para produção: mesmas filas, mesmo gerenciador de secrets, mesmos padrões de log.

### Funcionalidades

```
Environment
  python dev.py up                Sobe todos os serviços (migrations automáticas)
  python dev.py down              Para e remove todos os containers
  python dev.py build             Reconstrói as imagens Docker
  python dev.py restart           Reconstrói e reinicia tudo
  python dev.py logs              Acompanha eventos estruturados em tempo real
  python dev.py migrate           Roda as migrations manualmente se necessário

Tests
  python dev.py test              Suite completa com cobertura
  python dev.py test-unit         Unitários puros, sem Docker, sem banco
  python dev.py test-repositories Repositórios com PostgreSQL real
  python dev.py test-integration  Integração ponta a ponta
  python dev.py test-coverage     Gera relatório HTML de cobertura

Smoke tests
  python dev.py orders            Smoke test HTTP contra a API rodando
  python dev.py sqs-messages      Lê mensagens da fila principal
  python dev.py sqs-dlq           Lê mensagens da Dead Letter Queue
```

### Acompanhando eventos com python dev.py logs

O comando `python dev.py logs` é a forma mais direta de observar o sistema em funcionamento. Ele exibe apenas os logs estruturados JSON da API e do worker, filtrando os spans do OpenTelemetry que são redirecionados para stderr.

Exemplo de fluxo visível em tempo real ao criar uma ordem:

```json
{"method":"POST","path":"/orders","correlation_id":"abc-123","event":"request_received"}
{"order_id":"...","external_order_id":"ORD-001","event":"order_created","correlation_id":"abc-123"}
{"event_type":"order_created","order_id":"...","event":"outbox_processing_started","correlation_id":"abc-123"}
{"event_type":"order_created","order_id":"...","event":"outbox_event_published","correlation_id":"abc-123"}
{"event_type":"order_created","order_id":"...","event":"outbox_processing_completed","correlation_id":"abc-123"}
```

O `correlation_id` idêntico entre API e worker confirma que o mesmo evento está sendo rastreado de ponta a ponta, da requisição HTTP até a publicação no SQS.

### Bootstrap automático do ambiente virtual

Na primeira execução, o `dev.py` detecta que `.venv` não existe, cria o ambiente virtual e instala todas as dependências automaticamente. O único pré-requisito é ter Python 3.12+ instalado na máquina.

---

## Arquitetura

```
┌─────────────┐     ┌──────────────────────────────────────────────────────┐
│   Cliente    │────▶│  FastAPI Service                                    │
│  (HTTP)      │◀────│                                                      │
└─────────────┘     │  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
                    │  │   API   │─▶│ Services │─▶│  Repositories    │   │
                    │  │ (rotas) │  │ (negócio)│  │  (persistence)   │   │
                    │  └─────────┘  └────┬─────┘  └────────┬─────────┘   │
                    │                    │                  │             │
                    │              ┌─────▼─────┐     ┌─────▼──────┐     │
                    │              │  Clients  │     │ PostgreSQL │     │
                    │              │  (HTTP)   │     │ (orders +  │     │
                    │              └───────────┘     │  outbox)   │     │
                    └────────────────────────────────┴────────────┴─────┘

┌──────────────────┐     ┌─────────────┐
│  Outbox Worker   │────▶│  Amazon SQS │
│  (processo       │     │  (queue +   │
│   separado)      │     │   DLQ)      │
└──────────────────┘     └─────────────┘
```

### Camadas

| Camada | Diretório | Responsabilidade |
|--------|-----------|------------------|
| **API** | `app/api/` | Rotas FastAPI, schemas Pydantic, tratamento HTTP |
| **Domain** | `app/domain/` | Entidades, exceções de negócio, interfaces (ports) |
| **Services** | `app/services/` | Lógica de negócio pura, orquestração |
| **Repositories** | `app/repositories/` | Acesso ao banco via SQLAlchemy async |
| **Messaging** | `app/messaging/` | Publisher SQS e worker da outbox |
| **Clients** | `app/clients/` | Clientes HTTP externos com anti-corruption layer |
| **Observability** | `app/observability/` | Logs, métricas, tracing, middleware |
| **Config** | `app/config/` | Configurações e secrets |

---

## Diagramas C4

Os diagramas estão na pasta `diagrama c4/`.

### Nível 2: Container Diagram

Visão geral dos containers do sistema e como se comunicam.

![C4 Nível 2: Container Diagram](diagrama%20c4/c4-nivel2.png)

### Nível 3: Component Diagram

Zoom no interior do FastAPI Service, mostrando componentes internos e suas interações.

![C4 Nível 3: Component Diagram](diagrama%20c4/c4-nivel3.png)

---

## Como Rodar Localmente

### Pré-requisitos

- Docker e Docker Compose
- Python 3.12+

### Subindo o ambiente

```bash
python dev.py up
```

O comando sobe todos os serviços em ordem correta:

1. PostgreSQL aguarda ficar healthy
2. LocalStack aguarda ficar healthy (SQS + Secrets Manager)
3. Serviço `migrate` roda `alembic upgrade head` uma única vez e encerra
4. FastAPI Service e Worker sobem após a migration completar com sucesso
5. `dev.py` aguarda o `/health` responder antes de imprimir as URLs

Isso garante que **nunca há erros de tabela não encontrada** no worker, independente da velocidade da máquina.

Serviços iniciados:

- **PostgreSQL** na porta `5432`
- **LocalStack** na porta `4566` (SQS + Secrets Manager)
- **Requester Mock** na porta `8001` (simula o microsserviço externo)
- **FastAPI API** na porta `8000`
- **Outbox Worker** (processo separado, sem porta exposta)

### Testando a API

```bash
python dev.py orders
```

Ou via Swagger UI: http://localhost:8000/docs

Para testes manuais com cenários específicos:

```bash
# Solicitante nao encontrado (retorna 422)
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"external_order_id":"ORD-002","requester_id":"NOT-FOUND","description":"Teste"}'

# Servico indisponivel (retorna 503)
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"external_order_id":"ORD-003","requester_id":"ERROR","description":"Teste"}'

# Timeout (retorna 503)
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"external_order_id":"ORD-004","requester_id":"SLOW","description":"Teste"}'
```

O mock do requester service reconhece os IDs especiais `NOT-FOUND`, `ERROR` e `SLOW` para simular cada cenário de erro.

### Verificando filas SQS (LocalStack)

```bash
python dev.py sqs-messages   # fila principal
python dev.py sqs-dlq        # dead letter queue
```

---

## Testes

Os testes rodam **fora do container**, direto na máquina. O `testcontainers-python` sobe o PostgreSQL automaticamente via Docker quando necessário, sem precisar ter o `docker-compose` rodando.

A única dependência é ter o `.venv` configurado:

```bash
pip install -e ".[dev]"
```

### Executando

```bash
python dev.py test-unit         # unitários puros, sem Docker, sem banco
python dev.py test-repositories # repositórios com PostgreSQL real
python dev.py test-integration  # integração ponta a ponta
python dev.py test              # suite completa com cobertura
python dev.py test-coverage     # cobertura + abre relatório HTML
```

### Cobertura

| Módulo | O que é testado |
|--------|----------------|
| `test_order_service.py` | Lógica de negócio: criação, idempotência, erros de requester, race condition via IntegrityError |
| `test_repositories.py` | Persistência, constraint UNIQUE, SELECT FOR UPDATE SKIP LOCKED com sessões paralelas |
| `test_requester_client.py` | Mapeamento de 200/404/500/timeout para exceções de domínio |
| `test_worker.py` | Retry com backoff, falha após max retries, sleep não chamado na última tentativa |
| `test_create_order_api.py` | Fluxo HTTP completo, idempotência, correlation_id, todos os cenários de erro |

---

## Decisões Técnicas e Trade-offs

### Organização do projeto

As interfaces de contrato (`OrderRepositoryPort`, `RequesterClientPort`, `EventPublisherPort`) foram colocadas em `app/domain/ports.py` seguindo o princípio de que o domínio conhece os contratos de que precisa, mas não suas implementações concretas. Essa é uma simplificação consciente da arquitetura hexagonal: o domínio define o que precisa, as camadas de infra definem como entregar.

Em um projeto com maior volume de código, a alternativa seria uma pasta `interfaces/` dentro de cada camada que define o contrato (`repositories/interfaces.py`, `clients/interfaces.py`), mantendo o `domain/` apenas com entidades e exceções puras, alinhado com Clean Architecture.

A estrutura sem pasta `src/` é uma escolha pragmática comum em projetos FastAPI. Em um repositório de produção com múltiplos pacotes, `src/app/` seria preferível para evitar imports acidentais do diretório raiz.

### Ambiente local espelhando produção

O ambiente local usa LocalStack para simular SQS e Secrets Manager, e um mock do microsserviço de solicitantes. A decisão de investir nessa fidelidade local não é cosmética. Em projetos reais, divergências entre ambiente local e produção são uma das principais fontes de bugs que só aparecem em produção.

O `dev.py` formaliza esse ambiente: qualquer pessoa do time clona o repositório e executa `python dev.py up` para ter o mesmo ambiente rodando, independente do sistema operacional.

### Idempotência e chave de negócio

O requisito pede idempotência com "chave de negócio". Existem duas abordagens possíveis:

A primeira é **gerar a chave internamente**, derivando-a de campos do payload como `requester_id` + `order_date` + `service_type`. A vantagem é que o cliente não precisa gerenciar nada. O problema é que qualquer variação mínima entre retries do mesmo cliente quebra a idempotência, e a definição de quais campos formam a chave depende de regras de negócio que não estavam especificadas no desafio.

A segunda é **receber a chave do sistema de origem**, o que foi adotado aqui via `external_order_id`. Essa é a abordagem consolidada em APIs financeiras como Stripe e Adyen: o sistema que origina a ordem é responsável por garantir que retries usem o mesmo identificador. O serviço apenas garante que a mesma chave nunca gere duas ordens.

A estratégia é implementada em duas camadas para cobrir race conditions:

1. **Aplicação:** `find_by_external_id` antes do insert, retornando a ordem existente sem criar um novo insert
2. **Banco:** constraint `UNIQUE` no `external_order_id` como safety net. Mesmo que duas requisições simultâneas passem pela checagem da aplicação, apenas uma consegue fazer o insert e a outra recebe `IntegrityError` que é tratado como idempotência

Em caso de hit em qualquer das duas camadas: retorna **HTTP 200** com a ordem existente (não 409), para que retries automáticos do cliente funcionem de forma transparente.
### Transactional Outbox Pattern

O problema é que publicar no SQS e salvar no banco são duas operações distintas: não existe transação distribuída entre elas. Se o publish acontece antes do commit e o commit falha, o evento foi publicado para uma ordem inexistente. Se o commit acontece antes do publish e o publish falha, a ordem existe mas o evento é perdido para sempre.

A solução é salvar a ordem e o evento na **mesma transação do banco**. Um worker separado faz polling da tabela `outbox_events` e publica no SQS. A publicação só acontece depois que o commit está confirmado.

O trade-off é que a publicação não é imediata . Há a latência do polling interval (padrão: 5 segundos). Em troca, há garantia de que nenhum evento é perdido mesmo em caso de falha de infraestrutura. Essa consistência atende ao requisito não-funcional de tratamento de falhas.

### SELECT FOR UPDATE SKIP LOCKED

O problema aparece quando o worker escala horizontalmente (múltiplas instâncias rodando em paralelo), duas instâncias podem buscar os mesmos eventos pendentes e publicar o mesmo evento duas vezes no SQS.

`SELECT FOR UPDATE SKIP LOCKED` garante que cada instância do worker pega um lote exclusivo de eventos. Eventos já lockados por outra instância são ignorados em vez de aguardar o lock ser liberado, o que causaria filas e aumentaria latência.

Em caso de falha do worker: se o worker morrer após o lock mas antes do `mark_processed`, o lock é liberado automaticamente pelo PostgreSQL quando a conexão fecha. O evento permanece como `pending` e será reprocessado na próxima iteração, garantindo entrega *at-least-once*. O consumidor do SQS precisa ser idempotente para lidar com eventual duplicidade.

### Migration como serviço dedicado no Docker Compose

O serviço `migrate` no `docker-compose.yml` roda `alembic upgrade head` uma única vez e encerra com `restart: "no"`. A API e o worker declaram `condition: service_completed_successfully` no `depends_on`, garantindo que sobem somente após o schema estar pronto.

Essa abordagem elimina a necessidade de healthchecks no banco dentro da aplicação e evita erros de tabela não encontrada nos primeiros segundos de vida dos containers, problema comum em ambientes com inicialização paralela.

### Retry com Exponential Backoff

Falhas transitórias na publicação (rede, throttling do SQS) são tratadas com retry progressivo:

| Tentativa | Aguarda |
|-----------|---------|
| 1 | 1 segundo |
| 2 | 5 segundos |
| 3 | 30 segundos |
| Após tentativa 3 | Marca evento como `failed` e loga `outbox_processing_failed` |

Após esgotar as tentativas, o evento fica com status `failed` na outbox e requer intervenção manual ou processo de reconciliação, sem reprocessamento automático para evitar loops infinitos.

### Correlation ID

Cada requisição recebe um `correlation_id` (UUID v4) gerado no middleware. Se o cliente enviar o header `X-Correlation-ID`, o mesmo valor é reutilizado, útil para rastrear um retry específico nos logs do sistema de origem.

O `correlation_id` é propagado para: todos os logs da requisição via `contextvars`, o payload do evento publicado no SQS e o header `X-Correlation-ID` da resposta. Isso permite reconstruir o caminho completo de uma requisição através de todos os serviços e logs . Isso inclui quando a publicação acontece segundos depois no worker.

### Amazon SQS e LocalStack

SQS foi escolhido como fila de mensagens por ser o serviço gerenciado padrão no stack AWS, sem necessidade de gerenciar infraestrutura de Kafka ou RabbitMQ. A DLQ (`orders-dlq`) recebe mensagens que esgotaram os retries no worker.

LocalStack simula SQS e Secrets Manager localmente sem custo e sem conexão com a AWS real, mantendo o ambiente de desenvolvimento equivalente ao de produção nas interfaces utilizadas.

### AWS Secrets Manager

O Secrets Manager centraliza credenciais com suporte a rotação automática e integração com IAM um padrão consolidado em ambientes de produção fintech.

O fluxo implementado:

1. No startup, a aplicação carrega o secret `order-service-secrets` do Secrets Manager (ou LocalStack em dev)
2. Os valores são cacheados em memória durante o ciclo de vida do processo com uma única chamada por instância
3. Se o Secrets Manager não estiver disponível, o sistema faz fallback para as variáveis do `.env`

A separação entre **segredos** (Secrets Manager) e **configurações de comportamento** (variáveis de ambiente) é intencional. `db_password` e `api_key` são segredos vão para o Secrets Manager com rotação automática. `OTEL_ENABLED` e `LOG_LEVEL` são configurações de infraestrutura ficam em variáveis de ambiente do container, não no Secrets Manager.

> Em produção, os campos `db_password` e `api_key` não teriam valores default no `Settings`. Viriam obrigatoriamente do Secrets Manager. O fallback para `.env` existe exclusivamente para desenvolvimento local e testes.

### OpenTelemetry e Console Exporter

Tracing configurado com Console Exporter e controlado pela variável `OTEL_ENABLED`. Em desenvolvimento local fica `false` e os spans não são criados, sem poluir os logs estruturados. Em produção com `OTEL_ENABLED=true` injetado pelo orquestrador de containers, a troca para um exportador OTLP (AWS X-Ray, Jaeger, Datadog) exige apenas alterar `app/observability/tracing.py`, sem impacto no restante do código.

### structlog ao invés de logging padrão

JSON rendering nativo sem formatter customizado, processadores composáveis que permitem injetar `correlation_id` automaticamente em todos os logs da requisição via `contextvars`, sem precisar passar o ID manualmente para cada função.

### Ports e Adapters

As interfaces de domínio são definidas em `app/domain/ports.py` e implementadas em camadas separadas. O `OrderService` depende apenas das interfaces, nunca das implementações concretas. Isso permite trocar PostgreSQL, SQS ou o cliente HTTP sem tocar na lógica de negócio, e facilita o mock completo nos testes unitários.

---

## Observabilidade

### Logs Estruturados

Todos os logs são emitidos em JSON com `correlation_id` injetado automaticamente via `contextvars`:

```json
{"event": "order_created", "order_id": "...", "correlation_id": "...", "timestamp": "..."}
```

Eventos principais logados:

| Evento | Nível | Quando |
|--------|-------|--------|
| `request_received` | INFO | Toda requisição HTTP |
| `order_created` | INFO | Ordem criada com sucesso |
| `idempotency_hit` | INFO | Ordem já existia |
| `requester_not_found` | WARNING | Solicitante inválido (404) |
| `requester_unavailable` | ERROR | Serviço externo indisponível |
| `outbox_processing_started` | INFO | Worker iniciou processamento do evento |
| `outbox_event_published` | INFO | Evento publicado no SQS |
| `outbox_processing_completed` | INFO | Processamento concluído com sucesso |
| `outbox_processing_failed` | ERROR | Evento esgotou retries |
| `request_validation_failed` | WARNING | Payload inválido |

> Em produção os logs JSON são coletados pelo CloudWatch Logs Agent e podem ser consultados via CloudWatch Insights ou exportados para Grafana via datasource CloudWatch.

### Métricas

Endpoint `/metrics` expõe:

| Métrica | Tipo | Labels |
|---------|------|--------|
| `orders_created_total` | Counter | — |
| `orders_idempotent_total` | Counter | — |
| `orders_failed_total` | Counter | `error_type` |
| `messages_processed_total` | Counter | — |
| `messages_failed_total` | Counter | — |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint`, `status_code` |

### Tracing

Controlado por `OTEL_ENABLED` no `.env`. Desabilitado em desenvolvimento local para não poluir os logs estruturados. Em produção com `OTEL_ENABLED=true`, spans são instrumentados para:

- Request HTTP completo
- Chamada ao microsserviço de solicitantes
- Criação de ordem + outbox_event no banco
- Publicação de evento no SQS
- Processamento de cada mensagem no worker

---

## Sugestão de Arquitetura em Produção (AWS)

```
                    ┌──────────────┐
                    │ API Gateway  │
                    └──────┬───────┘
                           │
                    ┌──────▼──────┐
                    │ ECS Fargate │ ← FastAPI Service (auto-scaling)
                    │  (Tasks)    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼────┐ ┌────▼──────┐
        │    RDS     │ │  SQS   │ │ Secrets   │
        │ PostgreSQL │ │ Queue  │ │ Manager   │
        │ Multi-AZ   │ │ + DLQ  │ └───────────┘
        └───────────┘ └───┬────┘
                          │
                    ┌─────▼──────┐
                    │ ECS Fargate │ ← Outbox Worker (auto-scaling)
                    │  (Tasks)    │
                    └────────────┘

        CloudWatch → Logs + Métricas
        X-Ray      → Tracing distribuído
```

| Componente | Serviço AWS | Justificativa |
|------------|-------------|---------------|
| API | ECS Fargate | Containers serverless com auto-scaling sem gerenciar EC2 |
| Banco | RDS PostgreSQL Multi-AZ | Alta disponibilidade, failover automático, backups gerenciados |
| Filas | SQS Standard + DLQ | Totalmente gerenciado, sem infraestrutura de broker para manter |
| Secrets | Secrets Manager | Rotação automática de credenciais, integração nativa com IAM |
| Logs | CloudWatch Logs | Integração nativa com ECS, alertas e dashboards |
| Métricas | CloudWatch Metrics | Alarmes, auto-scaling baseado em métricas customizadas |
| Tracing | X-Ray | Tracing distribuído end-to-end com mapa de serviços |
| Gateway | API Gateway | Rate limiting, autenticação, WAF, throttling por rota |
