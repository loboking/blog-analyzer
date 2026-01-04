# Blog Analyzer Project

## Supabase 설정

- **SUPABASE_URL**: `https://xmkhsiscudfsqejqtkaf.supabase.co`
- **SUPABASE_KEY**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhta2hzaXNjdWRmc3FlanF0a2FmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjcyOTk4NjgsImV4cCI6MjA4Mjg3NTg2OH0.Selk0MkfqMAa1nptFuMnfFkz4LlhX7KCfzkDqhKJ6Xw`

## 로컬 서버 실행

```bash
SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhta2hzaXNjdWRmc3FlanF0a2FmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjcyOTk4NjgsImV4cCI6MjA4Mjg3NTg2OH0.Selk0MkfqMAa1nptFuMnfFkz4LlhX7KCfzkDqhKJ6Xw" python3 blog_analyzer_server.py
```

## 배포

- **GitHub**: https://github.com/loboking/blog-analyzer
- **서비스 URL**: https://blog-analyzer.onrender.com

## 데이터베이스 테이블

### blog_history
분석된 블로그 기록 저장
- `id`, `blog_id`, `blog_name`, `index_score`, `index_grade`, `analyzed_at`, `full_data`
