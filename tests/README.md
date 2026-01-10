# Tests

테스트 코드 디렉토리입니다.

## 구조

```
tests/
├── README.md
├── test_api.py          # API 엔드포인트 테스트 (추후 구현)
├── test_crawler.py      # 크롤러 테스트 (추후 구현)
└── test_calculator.py   # 지수 계산 테스트 (추후 구현)
```

## 테스트 실행

```bash
# pytest 설치
pip install pytest

# 테스트 실행
pytest tests/

# 커버리지 포함
pip install pytest-cov
pytest tests/ --cov=.
```

## 테스트 작성 가이드

### 테스트 파일 명명

- `test_*.py` 형식 사용

### 테스트 함수 명명

- `test_<기능>_<조건>_<예상결과>` 형식

```python
def test_analyze_valid_blog_id_returns_success():
    pass

def test_analyze_invalid_blog_id_returns_error():
    pass
```

## TODO

- [ ] API 엔드포인트 테스트 작성
- [ ] 크롤러 단위 테스트 작성
- [ ] 지수 계산 로직 테스트 작성
- [ ] CI에서 자동 테스트 실행
