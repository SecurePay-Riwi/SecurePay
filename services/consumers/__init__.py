"""Consumidores de las colas SQS de decisiones.

Cada consumidor es una función con la firma de AWS Lambda
(`handler(event, context)`): recibe un lote de hasta 10 mensajes de SQS y
devuelve cuáles fallaron (ReportBatchItemFailures). En AWS, SQS dispara la
Lambda solo; en local, `python -m services.consumers` lee las colas de
LocalStack y llama a la misma función.
"""
