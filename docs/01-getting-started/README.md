# Getting Started

네이버 블로그 지수 분석기 시작 가이드입니다.

## Prerequisites

- Python 3.11+
- pip (Python 패키지 관리자)
- Git

## Installation

### 1. 저장소 클론

```bash
git clone https://github.com/loboking/blog-analyzer.git
cd blog-analyzer
```

### 2. 가상환경 설정

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 환경 변수 설정

```bash
export SUPABASE_URL="https://xmkhsiscudfsqejqtkaf.supabase.co"
export SUPABASE_KEY="your-supabase-key"
```

## 로컬 서버 실행

```bash
SUPABASE_KEY="your-key" python3 blog_analyzer_server.py
```

서버가 시작되면 http://localhost:5000 에서 접속 가능합니다.

## Quick Start

### 블로그 분석 API 호출

```bash
curl "http://localhost:5000/api/analyze?blog_id=your_blog_id"
```

### Chrome 확장프로그램 설치

1. Chrome에서 `chrome://extensions` 접속
2. "개발자 모드" 활성화
3. "압축 해제된 확장 프로그램 로드" 클릭
4. `chrome-extension` 폴더 선택

## Next Steps

- [시스템 아키텍처](../02-architecture/README.md)
- [API 문서](../03-api/README.md)
- [개발 가이드](../04-development/README.md)
