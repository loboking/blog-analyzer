# API Documentation

네이버 블로그 지수 분석기 API 문서입니다.

## Base URL

- **로컬**: `http://localhost:5000`
- **프로덕션**: `https://blog-analyzer.onrender.com`

---

## Endpoints

### 블로그 분석

#### GET /api/analyze

블로그 ID로 지수를 분석합니다.

**Parameters**
| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| blog_id | string | O | 네이버 블로그 ID |

**Request**
```bash
curl "http://localhost:5000/api/analyze?blog_id=example_blog"
```

**Response**
```json
{
  "success": true,
  "blog_id": "example_blog",
  "blog_name": "블로그 이름",
  "index_score": 75,
  "index_grade": "최적1",
  "visitor_stats": {...},
  "post_stats": {...}
}
```

---

### 트렌딩 키워드

#### GET /api/trending-keywords

현재 트렌딩 키워드를 조회합니다.

**Request**
```bash
curl "http://localhost:5000/api/trending-keywords"
```

---

### 경쟁사 분석

#### POST /api/analyze-competitor

경쟁 블로그를 분석합니다.

**Request Body**
```json
{
  "blog_ids": ["blog1", "blog2", "blog3"]
}
```

---

### SEO 점수 계산

#### POST /api/calculate-seo-score

게시글의 SEO 점수를 계산합니다.

**Request Body**
```json
{
  "title": "게시글 제목",
  "content": "게시글 내용",
  "keyword": "타겟 키워드"
}
```

---

### 키워드 제안

#### GET /api/keyword-suggest

키워드 제안을 받습니다.

**Parameters**
| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| keyword | string | O | 기준 키워드 |

---

### 분석 이력

#### POST /api/save-history

분석 결과를 저장합니다.

#### GET /api/analysis-history/{blog_id}

블로그의 분석 이력을 조회합니다.

---

### 통계

#### GET /api/recent-blogs

최근 분석된 블로그 목록을 조회합니다.

#### GET /api/total-stats

전체 서비스 통계를 조회합니다.

---

### 커뮤니티

#### GET /api/community/posts

커뮤니티 게시물 목록을 조회합니다.

#### POST /api/community/posts

새 게시물을 작성합니다.

#### GET /api/community/posts/{post_id}

개별 게시물을 조회합니다.

---

## Error Responses

```json
{
  "success": false,
  "error": "에러 메시지"
}
```

## Rate Limiting

- 캐시 TTL: 5분
- 최대 캐시 크기: 100개
