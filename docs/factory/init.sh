#!/bin/bash
# GerarAI Mission Initialization Script
# Idempotent environment setup

set -e

echo "🚀 Initializing GerarAI mission environment..."

# Check prerequisites
command -v node >/dev/null 2>&1 || { echo "❌ Node.js not found"; exit 1; }
command -v uv >/dev/null 2>&1 || { echo "❌ uv not found"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ Docker not found"; exit 1; }

# Frontend dependencies
if [ ! -d "node_modules" ]; then
  echo "📦 Installing frontend dependencies..."
  npm install
else
  echo "✅ Frontend dependencies already installed"
fi

# Backend dependencies
if [ ! -d "data-engine/.venv" ]; then
  echo "📦 Installing backend dependencies..."
  cd data-engine
  uv sync --frozen --extra test --extra dev --no-install-project
  cd ..
else
  echo "✅ Backend dependencies already installed"
fi

# Check services are running
echo "🔍 Checking required services..."

if ! pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
  echo "⚠️  Postgres not running. Start with: docker compose up -d postgres"
fi

if ! redis-cli -p 6379 ping >/dev/null 2>&1; then
  echo "⚠️  Redis not running. Start with: docker compose up -d redis"
fi

if ! curl -sf http://localhost:6333/healthz >/dev/null 2>&1; then
  echo "⚠️  Qdrant not running. Start with: docker compose up -d qdrant"
fi

if ! curl -sf http://localhost:9000/minio/health/live >/dev/null 2>&1; then
  echo "⚠️  MinIO not running. Start with: docker compose up -d minio"
fi

echo "✅ Mission environment initialized"
echo ""
echo "Next steps:"
echo "  1. Start services: docker compose up -d postgres redis qdrant minio"
echo "  2. Run migrations: cd data-engine && alembic upgrade head"
echo "  3. Start backend: cd data-engine && uvicorn app.main:app --reload"
echo "  4. Start frontend: npm run dev"
