# Seed de datos — PagoSeguro Antifraude

Genera datos sintéticos reproducibles para el desarrollo local: usuarios, dispositivos, comercios y listas restrictivas.

## ¿Qué hace?

Puebla la base de datos PostgreSQL con datos de prueba que simulan el entorno real de PagoSeguro. Los datos son:

- **Reproducibles:** con la misma semilla, genera exactamente los mismos datos.
- **Idempotentes:** ejecutarlo varias veces no duplica registros.
- **Parametrizables:** el volumen se ajusta con variables de entorno.
- **Con integridad referencial:** los dispositivos siempre pertenecen a un usuario existente.

## Requisitos

- Python 3.10+
- PostgreSQL 16+
- Entorno virtual activo (`venv/`)


