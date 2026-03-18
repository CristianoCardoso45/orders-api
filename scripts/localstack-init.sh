#!/bin/bash
# Script de inicialização do LocalStack.
# Executado automaticamente quando o container fica pronto.
# Cria as filas SQS e secrets necessários para desenvolvimento local.

set -euo pipefail

echo "=== Inicializando recursos do LocalStack ==="

# ── Criar Dead Letter Queue primeiro (a DLQ precisa existir antes da fila principal) ──
echo "Criando DLQ: orders-dlq"
awslocal sqs create-queue \
  --queue-name orders-dlq \
  --region us-east-1

# Obter ARN da DLQ para configurar redrive policy
DLQ_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/orders-dlq \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)

echo "DLQ ARN: $DLQ_ARN"

# ── Criar fila principal com redrive policy apontando para DLQ ──
# maxReceiveCount=3: após 3 tentativas de processamento com falha,
# a mensagem é movida automaticamente para a DLQ
echo "Criando fila principal: orders-queue"
awslocal sqs create-queue \
  --queue-name orders-queue \
  --attributes "{\"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"${DLQ_ARN}\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"}" \
  --region us-east-1

# ── Criar secret no Secrets Manager ──
echo "Criando secret: order-service-secrets"
awslocal secretsmanager create-secret \
  --name order-service-secrets \
  --secret-string '{"db_password":"orders_pass","api_key":"dev-api-key"}' \
  --region us-east-1

echo "=== LocalStack inicializado com sucesso ==="
awslocal sqs list-queues --region us-east-1
