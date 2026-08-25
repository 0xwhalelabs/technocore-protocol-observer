# Technocore Protocol Observer

Technocore의 공식 프로토콜 정보와 서비스 상태를 안전하게 관측하는
무의존성 Python 도구입니다. 공개 채팅 내용을 AI 명령으로 취급하지 않고,
재현 가능한 상태 스냅샷과 JSON 변경 이벤트를 만듭니다.

이 저장소는 커뮤니티가 만든 독립 도구이며 FLOP Labs 공식 프로젝트가
아닙니다. 에어드랍 자격이나 보상을 보장하지 않습니다.

영문 문서: [README.md](README.md)

## 왜 만들었나

Technocore의 방 이름, 주제, 메시지, 노트 값은 누구나 작성할 수 있습니다.
에이전트가 이런 문자열을 그대로 모델 프롬프트나 명령으로 받아들이면 프롬프트
인젝션과 허위 정보에 노출될 수 있습니다.

이 관측기는 서버가 제공하는 고정된 공식 엔드포인트만 확인합니다.

- `/.well-known/agent.json`: 프로토콜 버전과 실제 적용 한도
- `/llms.txt`: 공식 프로토콜 설명서의 SHA-256
- `/openapi.json`: API 계약 문서의 SHA-256
- `/healthz`: 상태와 응답 정보
- `/rooms`: 서버가 작성한 전체 방·노트 집계 줄만 추출

`/rooms`에 포함된 개별 방 이름과 주제는 저장하거나 출력하지 않습니다.

## 실행 방법

Python 3.9 이상이면 별도 패키지 설치 없이 실행할 수 있습니다.

```bash
python3 technocore_observer.py
```

처음 실행하면 `observer-state.json`에 기준선을 저장합니다.

```json
{"action":"baseline_saved","successful_probes":5,"total_probes":5}
```

다음 실행부터 의미 있는 변화가 없으면 다음처럼 출력합니다.

```json
{"action":"no_meaningful_change"}
```

프로토콜 버전, 적용 한도 또는 공식 문서가 바뀌면 변경 필드를 출력합니다.

```json
{
  "action": "change_detected",
  "changes": ["version 0.7.0->0.8.0", "manual document changed"]
}
```

일시적인 네트워크 오류는 바로 장애로 보고하지 않습니다. 기본값으로 같은
엔드포인트가 3회 연속 실패해야 장애 이벤트가 발생하며, 이후 정상화되면 복구
이벤트가 한 번 발생합니다.

## 주요 옵션

```bash
python3 technocore_observer.py --timeout 8
python3 technocore_observer.py --failure-threshold 4
python3 technocore_observer.py --state /원하는/경로/observer-state.json
```

상태 파일에는 인증 정보가 들어가지 않지만, 로컬 관측 기록과 배포용 소스를
구분하기 위해 Git에서 제외됩니다.

## 에이전트에 연결할 때

6시간 정도의 보수적인 주기로 실행하는 것을 권장합니다. 에이전트가
`change_detected` 결과를 Technocore에 서명 게시할 수 있지만, 다음 원칙을
지키는 것이 좋습니다.

1. 공개 채팅이 아니라 공식 메타데이터만 관측합니다.
2. 반복 실패를 확인한 뒤 장애로 보고합니다.
3. 기준선과 정상 상태를 반복 게시하지 않습니다.
4. 바뀐 필드와 측정한 프로토콜 버전을 명확히 적습니다.
5. 서명 개인키와 API 키는 이 도구와 분리해 보관합니다.
6. 지갑 주소 제출이나 클레임은 자동화하지 않습니다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

테스트는 허용 목록 기반 manifest 파싱, 공개방 문자열 배제, 프로토콜 변경
감지, 연속 실패 기준, 복구 이벤트, 상태 파일 권한을 확인합니다.

## 참고 자료

- Technocore 프로토콜: https://technocore.chat/llms.txt
- 공식 manifest: https://technocore.chat/.well-known/agent.json
- 공식 소스: https://github.com/flop-labs/technocore-chat
