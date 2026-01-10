# Operations Guide

운영 및 유지보수 가이드입니다.

## 모니터링

### 서비스 상태 확인

```bash
curl -I https://blog-analyzer.onrender.com/
```

### 로그 확인

- Render Dashboard > Logs

## 문제 해결

### 서버 응답 없음

1. Render Dashboard에서 서비스 상태 확인
2. 로그에서 에러 메시지 확인
3. 필요시 서비스 재시작

### 크롤링 실패

- 네이버 블로그 구조 변경 확인
- User-Agent 헤더 확인
- IP 차단 여부 확인

### 데이터베이스 연결 실패

1. Supabase 서비스 상태 확인
2. API 키 유효성 확인
3. 네트워크 연결 확인

## 유지보수

### 의존성 업데이트

```bash
pip install --upgrade <package>
pip freeze > requirements.txt
```

### 캐시 관리

- 캐시 TTL: 5분
- 최대 캐시 크기: 100개
- 서버 재시작 시 캐시 초기화

## 백업

### 데이터베이스 백업

Supabase Dashboard에서 자동 백업 설정 가능

## 보안

- SUPABASE_KEY는 환경 변수로만 관리
- .env 파일은 .gitignore에 포함
- CORS 설정으로 허용된 도메인만 접근
