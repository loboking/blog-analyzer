# Development Guide

개발 환경 설정 및 워크플로우 가이드입니다.

## 개발 환경 설정

### 필수 도구

- Python 3.11+
- Node.js (Chrome 확장 개발 시)
- Git

### 가상환경 활성화

```bash
source venv/bin/activate
```

### 의존성 추가

```bash
pip install <package>
pip freeze > requirements.txt
```

## 코드 컨벤션

### Python

- PEP 8 스타일 가이드 준수
- 함수/클래스에 docstring 작성
- 타입 힌트 권장

### JavaScript

- ES6+ 문법 사용
- camelCase 네이밍

## 브랜치 전략

```
main          # 프로덕션 배포
├── develop   # 개발 통합
│   ├── feature/xxx
│   └── bugfix/xxx
```

## 커밋 메시지

```
<type>: <subject>

예시:
feat: 새로운 기능 추가
fix: 버그 수정
docs: 문서 수정
refactor: 코드 리팩토링
```

## 테스트

```bash
# 테스트 실행 (추후 구현)
pytest tests/
```

## 로컬 서버 실행

```bash
SUPABASE_KEY="your-key" python3 blog_analyzer_server.py
```
