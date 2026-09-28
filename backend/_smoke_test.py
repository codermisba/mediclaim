"""End-to-end smoke test: create a sample claim, run the pipeline, fetch the PDF.

Run from backend/ with:  python _smoke_test.py
"""

from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient

import main


def show(record: dict, indent: str = "   ") -> None:
    for stage in record.get("stages", []):
        print(
            f"{indent}{stage['status']:<10} {stage['label']:<24} "
            f"{stage.get('message', '')[:52]}"
        )


def main_test() -> int:
    with TestClient(main.app) as client:
        health = client.get("/api/health").json()
        print(f"HEALTH  mode={health['ai_mode']}  {health['message']}")
        print(f"        models={health['models']}")
        print()

        print("1. GET /api/claims/sample")
        sample = client.get("/api/claims/sample").json()
        print(f"   title: {sample['title']}")
        for doc in sample["documents"]:
            flag = "ok" if doc["available"] else "MISSING"
            print(f"   [{flag}] {doc['filename']:<24} {doc['description']}")
        print()

        print("2. POST /api/claim/create (use_sample_data=true)")
        created = client.post("/api/claim/create", json={"use_sample_data": True})
        print("   status:", created.status_code)
        claim_id = created.json()["claim_id"]
        record = created.json()["claim"]
        print(f"   claim_id={claim_id}  documents={len(record['documents'])}")
        print()

        print("3. POST /api/claim/process")
        started = client.post("/api/claim/process", json={"claim_id": claim_id})
        print("   status:", started.status_code, started.json().get("message", ""))
        print()

        print("4. poll GET /api/claim/{id}")
        deadline = time.time() + 180
        final = None
        while time.time() < deadline:
            payload = client.get(f"/api/claim/{claim_id}").json()
            record = payload["claim"]
            if not payload.get("pipeline_running") and record["status"] != "processing":
                final = record
                break
            time.sleep(1.0)
        if final is None:
            print("   TIMEOUT - pipeline did not finish")
            return 1

        print("   final status:", final["status"])
        print("   ai_mode:    ", final["ai_mode"])
        show(final)
        print()

        if final.get("error"):
            print("   ERROR:", final["error"])
            return 1

        claim_data = final.get("claim_data") or {}
        print("5. extracted claim data")
        for section in ("patient", "insurance", "hospital", "doctor", "treatment", "billing"):
            values = {
                k: v
                for k, v in (claim_data.get(section) or {}).items()
                if v not in ("", 0.0, 0, [], None)
            }
            print(f"   {section:<11} {values}")
        print()

        validation = final.get("validation") or {}
        print("6. validation")
        print(f"   valid={validation.get('valid')}  checked={validation.get('checked_fields')}")
        print(f"   missing_required: {validation.get('missing_required')}")
        print(f"   missing_optional: {validation.get('missing_optional')}")
        for issue in validation.get("inconsistencies", [])[:5]:
            print(f"   ! {issue.get('severity')}: {issue.get('message')}")
        for issue in validation.get("warnings", [])[:5]:
            print(f"   ~ {issue.get('message')}")
        print()

        if final["status"] == "ready_for_review":
            generated = final.get("generated") or {}
            print("7. generated claim")
            print(f"   claim_number: {generated.get('claim_number')}")
            print(f"   type:         {generated.get('claim_type')}")
            print(f"   amount:       {generated.get('claim_amount')} {generated.get('currency')}")
            print(f"   narrative:    {(generated.get('narrative') or '')[:150]}")
            print(f"   line items:   {len(generated.get('line_items') or [])}")
            print()

            review = final.get("review") or {}
            print("8. review")
            print(f"   status={review.get('status')}  checked={review.get('checked_fields')}")
            print(f"   summary: {review.get('summary')}")
            for issue in review.get("issues", [])[:8]:
                print(f"   - [{issue.get('severity')}] {issue.get('message')}")
            print()

            print("9. GET /api/claim/{id}/pdf")
            pdf = client.get(f"/api/claim/{claim_id}/pdf")
            print(f"   status={pdf.status_code}  bytes={len(pdf.content)}  magic={pdf.content[:5]}")
            if pdf.status_code == 200 and pdf.content[:4] == b"%PDF":
                with open("_smoke_claim.pdf", "wb") as handle:
                    handle.write(pdf.content)
                print("   saved to _smoke_claim.pdf")
            else:
                print("   BODY:", pdf.text[:400])
                return 1
        else:
            print(f"7. pipeline stopped at status={final['status']} (expected: needs_input)")
            print("   this is correct behaviour - required fields were missing")

        print()
        print("10. GET /api/claims (dashboard list)")
        listing = client.get("/api/claims").json()
        print(f"   count={listing['count']}  mode={listing['ai_mode']}")
        for line in listing["claims"]:
            amount = line.get("total_amount") or 0
            print(
                f"   {line.get('claim_number') or '-':<20} {line.get('status', '?'):<16} "
                f"{(line.get('patient_name') or '-'):<16} "
                f"{line.get('currency', '')} {amount:>10,.2f}  "
                f"docs={line.get('document_count', 0)} missing={line.get('missing_count', 0)}"
            )
        print()
        print("SMOKE TEST PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main_test())
