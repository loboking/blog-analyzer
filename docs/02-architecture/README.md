# Architecture

네이버 블로그 지수 분석기 시스템 아키텍처입니다.

## Overview

Flask 기반 백엔드 서버와 Chrome 확장프로그램으로 구성된 블로그 분석 서비스입니다.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Chrome 확장    │────▶│  Flask 서버     │────▶│   Supabase      │
│  (popup.js)     │     │  (Python)       │     │  (PostgreSQL)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │  네이버 블로그   │
                        │  (크롤링 대상)   │
                        └─────────────────┘
```

## Components

### Backend Server (blog_analyzer_server.py)

- **NaverBlogCrawler**: 네이버 블로그 데이터 크롤링
- **Flask API**: RESTful API 엔드포인트 제공
- **Supabase 연동**: 분석 결과 저장/조회
- **캐싱**: 5분 TTL 메모리 캐시

### Chrome Extension (chrome-extension/)

- **Manifest v3** 기반
- **Content Script**: DOM에서 통계 데이터 추출
- **Popup UI**: 분석 결과 시각화

### Database (Supabase)

- **blog_history** 테이블: 분석 기록 저장
- REST API 직접 호출 방식

## Data Flow

1. 사용자가 블로그 ID 입력
2. Flask 서버가 네이버 블로그 크롤링
3. 지수 계산 알고리즘 적용
4. 결과를 Supabase에 저장
5. 클라이언트에 JSON 응답

## Diagrams

- [시스템 구조도](./diagrams/)
- [데이터 흐름도](./diagrams/)

## Design Decisions

- **Flask 선택**: 경량 웹 프레임워크, 빠른 개발
- **BeautifulSoup**: 안정적인 HTML 파싱
- **Supabase**: 서버리스 PostgreSQL, REST API 지원
- **Render 배포**: 무료 티어, Git 연동 자동 배포
