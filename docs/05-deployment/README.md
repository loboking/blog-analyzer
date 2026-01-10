# Deployment Guide

배포 환경 설정 및 가이드입니다.

## Render 배포

### 자동 배포

GitHub main 브랜치에 푸시하면 자동으로 배포됩니다.

### 수동 배포

1. [Render Dashboard](https://dashboard.render.com) 접속
2. blog-analyzer 서비스 선택
3. "Manual Deploy" 클릭

### 환경 변수

Render Dashboard에서 설정:

| 변수 | 설명 |
|------|------|
| SUPABASE_URL | Supabase 프로젝트 URL |
| SUPABASE_KEY | Supabase API 키 |
| PYTHON_VERSION | Python 버전 (3.11) |

### 서비스 설정 (render.yaml)

```yaml
services:
  - type: web
    name: blog-analyzer
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn blog_analyzer_server:app --bind 0.0.0.0:$PORT --timeout 120 --workers 4 --threads 2
```

## 프로덕션 URL

- **서비스**: https://blog-analyzer.onrender.com
- **GitHub**: https://github.com/loboking/blog-analyzer

## 모니터링

### 로그 확인

Render Dashboard > Logs 탭에서 실시간 로그 확인

### 헬스 체크

```bash
curl https://blog-analyzer.onrender.com/
```

## 롤백

1. Render Dashboard > Deploys 탭
2. 이전 배포 선택
3. "Rollback to this deploy" 클릭
