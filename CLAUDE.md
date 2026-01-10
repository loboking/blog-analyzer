# Blog Analyzer Project

네이버 블로그 지수 분석기

## Quick Start

```bash
# 로컬 서버 실행
SUPABASE_KEY="your-key" python3 blog_analyzer_server.py
```

## Project Structure

```
blog수치/
├── docs/                    # 문서
├── tests/                   # 테스트
├── chrome-extension/        # Chrome 확장프로그램
├── blog_analyzer_server.py  # 메인 서버
└── .github/workflows/       # CI/CD
```

## Supabase 설정

- **SUPABASE_URL**: `https://xmkhsiscudfsqejqtkaf.supabase.co`
- **SUPABASE_KEY**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhta2hzaXNjdWRmc3FlanF0a2FmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjcyOTk4NjgsImV4cCI6MjA4Mjg3NTg2OH0.Selk0MkfqMAa1nptFuMnfFkz4LlhX7KCfzkDqhKJ6Xw`

## 배포

- **GitHub**: https://github.com/loboking/blog-analyzer
- **서비스 URL**: https://blog-analyzer.onrender.com

## 데이터베이스 테이블

### blog_history
분석된 블로그 기록 저장
- `id`, `blog_id`, `blog_name`, `index_score`, `index_grade`, `analyzed_at`, `full_data`

---

## Token Optimization Rules

### File Reading
- 대용량 파일은 필요한 부분만 읽기
- `blog_analyzer_server.py`는 11,000줄 이상 - 전체 읽기 지양

### Search Strategy
- Grep으로 특정 함수/클래스 검색 후 해당 부분만 읽기
- 예: `Grep "def analyze"` → 해당 라인 범위만 Read

### Key Files
| 파일 | 용도 | 크기 |
|------|------|------|
| blog_analyzer_server.py | 메인 서버 | 11,000줄 |
| chrome-extension/content.js | 콘텐츠 스크립트 | 7,600줄 |

### API Endpoints (Quick Reference)
- `/api/analyze` - 블로그 분석
- `/api/trending-keywords` - 트렌딩 키워드
- `/api/save-history` - 이력 저장

### Common Patterns
```python
# Flask 라우트 패턴
@app.route('/api/...', methods=['GET', 'POST'])
def endpoint():
    ...

# 크롤러 클래스
class NaverBlogCrawler:
    def crawl(self):
        ...
```
