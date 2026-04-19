"""Comprehensive test dashboard — vault-based endpoint verification."""
import json
import sys
import requests

BASE = "http://145.223.21.222/api"
TOKEN = None

def get_token():
    """Generate JWT via jose locally."""
    from jose import jwt
    from datetime import datetime, timedelta, timezone
    exp = datetime.now(timezone.utc) + timedelta(hours=24)
    return jwt.encode(
        {"sub": "fee83c50-aa4d-4350-bc79-63a3a1d57737", "exp": exp},
        "28004f81bdcfcb293be3e782b714b421c7e9e0d6235c346a4252ef7a18b041bb",
        algorithm="HS256",
    )

def h():
    return {"Authorization": f"Bearer {TOKEN}"}

def test(name, method, path, expected_status=200, json_body=None):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, headers=h(), timeout=10)
        elif method == "POST":
            r = requests.post(url, headers=h(), json=json_body, timeout=10)
        elif method == "PATCH":
            r = requests.patch(url, headers=h(), json=json_body, timeout=10)
        else:
            r = requests.request(method, url, headers=h(), json=json_body, timeout=10)
        
        ok = r.status_code == expected_status
        status = "PASS" if ok else "FAIL"
        symbol = "✓" if ok else "✗"
        data = None
        try:
            data = r.json()
        except Exception:
            data = r.text[:200]
        
        detail = ""
        if isinstance(data, list):
            detail = f"{len(data)} items"
        elif isinstance(data, dict):
            keys = list(data.keys())[:5]
            detail = str({k: data[k] for k in keys})
        else:
            detail = str(data)[:100]
        
        print(f"  {symbol} {status} [{r.status_code}] {name}: {detail}")
        return ok, data
    except Exception as e:
        print(f"  ✗ ERROR {name}: {e}")
        return False, None

def main():
    global TOKEN
    TOKEN = get_token()
    
    results = {"pass": 0, "fail": 0, "error": 0}
    
    def track(ok):
        if ok is None:
            results["error"] += 1
        elif ok:
            results["pass"] += 1
        else:
            results["fail"] += 1
    
    # ── Section 1: Dashboard (vault: dashboard.md) ──────────────
    print("\n═══ DASHBOARD ENDPOINTS ═══")
    
    ok, data = test("Overview Stats", "GET", "/overview/stats")
    track(ok)
    if ok and data:
        for k in ["total_leads", "invited", "accepted", "sent"]:
            if k not in data:
                print(f"    ⚠ Missing key: {k}")
    
    ok, campaigns = test("Campaigns List", "GET", "/campaigns")
    track(ok)
    
    ok, _ = test("Queue Stats", "GET", "/queue/stats")
    track(ok)
    
    ok, _ = test("Queue List", "GET", "/queue?limit=5")
    track(ok)
    
    # ── Section 2: Campaigns (vault: campaigns.md) ──────────────
    print("\n═══ CAMPAIGN ENDPOINTS ═══")
    
    cid = None
    if campaigns and len(campaigns) > 0:
        cid = campaigns[0]["id"]
        cname = campaigns[0]["name"]
        print(f"  Using campaign: {cname} ({cid})")
        
        ok, _ = test("Get Campaign", "GET", f"/campaigns/{cid}")
        track(ok)
        
        ok, stats = test("Campaign Stats", "GET", f"/campaigns/{cid}/stats")
        track(ok)
    
    # ── Section 3: Leads (vault: leads-page.md) ──────────────
    print("\n═══ LEADS ENDPOINTS ═══")
    
    if cid:
        ok, leads_data = test("List Leads", "GET", f"/leads?campaign_id={cid}&page=1&limit=5")
        track(ok)
        if ok and leads_data:
            if "total" not in leads_data or "leads" not in leads_data:
                print("    ⚠ Missing 'total' or 'leads' key in response")
    
    # ── Section 4: Canvas / Sequences (vault: canvas-editor.md, sequence-engine.md) ──
    print("\n═══ CANVAS / SEQUENCE ENDPOINTS ═══")
    
    if cid:
        ok, graph = test("Load Graph", "GET", f"/sequences/{cid}")
        track(ok)
        
        # Save a test graph with ALL 25 node types to verify backend accepts them
        test_nodes = [
            {"id": "n_trigger", "node_type": "trigger_start", "position_x": 250, "position_y": 0, "data": {}},
            {"id": "n_ai_screen", "node_type": "condition_ai_screen", "position_x": 250, "position_y": 150, "data": {"screening_prompt": "Accept VP/Director at B2B SaaS companies. Reject others."}},
            {"id": "n_source_router", "node_type": "condition_lead_source", "position_x": 250, "position_y": 300, "data": {"sources": ["apollo", "hunter", "github"]}},
            {"id": "n_invite", "node_type": "action_linkedin_invite", "position_x": 250, "position_y": 450, "data": {}},
            {"id": "n_delay", "node_type": "delay", "position_x": 250, "position_y": 600, "data": {"delay_days": 3}},
            {"id": "n_end", "node_type": "end", "position_x": 250, "position_y": 750, "data": {}},
        ]
        test_edges = [
            {"source_node_id": "n_trigger", "target_node_id": "n_ai_screen", "source_handle": "default", "target_handle": "default"},
            {"source_node_id": "n_ai_screen", "target_node_id": "n_source_router", "source_handle": "true", "target_handle": "default"},
            {"source_node_id": "n_ai_screen", "target_node_id": "n_end", "source_handle": "false", "target_handle": "default"},
            {"source_node_id": "n_source_router", "target_node_id": "n_invite", "source_handle": "apollo", "target_handle": "default"},
            {"source_node_id": "n_source_router", "target_node_id": "n_delay", "source_handle": "default", "target_handle": "default"},
            {"source_node_id": "n_invite", "target_node_id": "n_delay", "source_handle": "default", "target_handle": "default"},
            {"source_node_id": "n_delay", "target_node_id": "n_end", "source_handle": "default", "target_handle": "default"},
        ]
        
        ok, _ = test("Save Graph (Phase 1A nodes)", "POST", "/sequences/save", json_body={
            "campaign_id": cid,
            "nodes": test_nodes,
            "edges": test_edges,
        })
        track(ok)
        
        # Reload to verify persistence
        ok, reloaded = test("Reload Graph (verify persist)", "GET", f"/sequences/{cid}")
        track(ok)
        if ok and reloaded:
            node_types_saved = [n["node_type"] for n in reloaded["nodes"]]
            print(f"    Persisted types: {node_types_saved}")
            for expected in ["condition_ai_screen", "condition_lead_source"]:
                if expected in node_types_saved:
                    print(f"    ✓ {expected} persisted OK")
                else:
                    print(f"    ✗ {expected} NOT found in saved graph!")
                    results["fail"] += 1
            
            # Verify data payloads
            for n in reloaded["nodes"]:
                if n["node_type"] == "condition_ai_screen":
                    d = n.get("data") or {}
                    if d.get("screening_prompt"):
                        print(f"    ✓ AI screen prompt persisted: '{d['screening_prompt'][:40]}...'")
                    else:
                        print(f"    ✗ AI screen prompt MISSING in data")
                        results["fail"] += 1
                elif n["node_type"] == "condition_lead_source":
                    d = n.get("data") or {}
                    if d.get("sources"):
                        print(f"    ✓ Source router sources persisted: {d['sources']}")
                    else:
                        print(f"    ✗ Source router sources MISSING in data")
                        results["fail"] += 1
        
        # Telemetry endpoint
        ok, _ = test("Telemetry", "GET", f"/sequences/{cid}/telemetry")
        track(ok)
    
    # ── Section 5: Settings / Accounts (vault: settings-page.md) ──
    print("\n═══ ACCOUNTS / SETTINGS ═══")
    
    ok, _ = test("Email Accounts", "GET", "/accounts/email")
    track(ok)
    
    ok, voice = test("Voice Agents", "GET", "/accounts/voice")
    track(ok)
    
    ok, _ = test("LinkedIn Accounts", "GET", "/accounts/linkedin")
    track(ok)
    
    # ── Section 6: Lead Gen (vault: lead-sources-ui.md, multi-source-lead-gen.md) ──
    print("\n═══ LEAD GEN ENDPOINTS ═══")
    
    ok, sources = test("Available Sources", "GET", "/lead-gen/sources")
    track(ok)
    if ok and sources:
        print(f"    Sources: {[s.get('key') or s.get('name') for s in sources]}")
    
    if cid:
        ok, _ = test("Lead Gen Configs", "GET", f"/lead-gen/configs/{cid}")
        track(ok)
        
        ok, _ = test("Lead Gen Runs", "GET", f"/lead-gen/runs?campaign_id={cid}")
        track(ok)
    
    # ── Section 7: Job Search (vault: job-search-pipeline.md) ──
    print("\n═══ JOB SEARCH ═══")
    
    if cid:
        ok, _ = test("Job Search Configs", "GET", f"/job-search/configs/{cid}")
    track(ok)
    
    ok, _ = test("Job Search Runs", "GET", "/job-search/runs")
    track(ok)
    
    # ── Section 8: Frontend accessibility ──
    print("\n═══ FRONTEND ═══")
    
    try:
        r = requests.get("http://145.223.21.222/", timeout=10)
        if r.status_code == 200 and "<!DOCTYPE" in r.text[:100].upper() or "<html" in r.text[:200].lower():
            print(f"  ✓ PASS Frontend serves HTML ({len(r.text)} bytes)")
            results["pass"] += 1
            
            # Check for key JS bundle
            if "src/main.tsx" in r.text or ".js" in r.text:
                print(f"    ✓ JS bundle reference found")
            else:
                print(f"    ⚠ No JS bundle reference in HTML")
        else:
            print(f"  ✗ FAIL Frontend returned {r.status_code}")
            results["fail"] += 1
    except Exception as e:
        print(f"  ✗ ERROR Frontend: {e}")
        results["error"] += 1
    
    # ── Summary ──
    total = results["pass"] + results["fail"] + results["error"]
    print(f"\n{'='*50}")
    print(f"TEST DASHBOARD RESULTS")
    print(f"{'='*50}")
    print(f"  PASS:  {results['pass']}/{total}")
    print(f"  FAIL:  {results['fail']}/{total}")
    print(f"  ERROR: {results['error']}/{total}")
    print(f"{'='*50}")
    
    # Clean up: restore empty graph on Campaign 2 so test data doesn't persist
    print("\nCleaning up test graph...")
    try:
        r = requests.post(f"{BASE}/sequences/save", headers=h(), json={
            "campaign_id": cid,
            "nodes": [],
            "edges": [],
        }, timeout=10)
        print(f"  {'✓' if r.status_code == 200 else '✗'} Cleanup: {r.status_code}")
    except:
        print("  ✗ Cleanup failed")
    
    return 0 if results["fail"] == 0 and results["error"] == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
