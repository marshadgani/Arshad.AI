"""Orchestrator — runs the 9-agent pipeline end-to-end.

Sequence:
    1. BA           → RTM + BPDD
    2. EA pre-build → ArchReviewSignoff (rejects halt the pipeline)
    3. SA           → SDD
    4. Developer    → FeatureCode (paths checked against denylist)
    5. Process Org  → POOutput (then update_phd writes the file)
    6. TSW          → TestScripts
    7. Tester       → DefectCatalogue (iter 0)
    8. Bug-fix loop → BugFixer + Tester until defects=[] or MAX_ITERATIONS
    9. EA post-build (always runs, even on partial halt)

Live-mode (Q2=b): after step 9, the orchestrator creates branch
`dev-team/<FEAT-NNN>-<slug>`, writes generated files into the working
tree, and commits. The user merges manually.
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .agents.base import DevAgent  # noqa: F401 — re-exported for typing
from .agents.bug_fixer import BugFixer, BugFixRequest
from .agents.business_analyst import BARequest, BusinessAnalyst
from .agents.developer import Developer, DevRequest, is_path_allowed
from .agents.enterprise_architect import EARequest, EnterpriseArchitect
from .agents.process_organiser import PORequest, ProcessOrganiser
from .agents.solution_architect import SARequest, SolutionArchitect
from .agents.test_script_writer import TestScriptWriter, TSWRequest
from .agents.tester import Tester, TesterRequest
from .artifacts import (
    DefectCatalogue,
    FeatureCode,
    PHEntry,
    PipelineResult,
)
from .feature_id import next_feature_id, slug_from_requirement
from .process_hierarchy import update_phd
from .storage import (
    log_pipeline_run_row,
    now_iso,
    relative_to_repo,
    repo_root,
)

_log = logging.getLogger(__name__)
MAX_ITERATIONS = 5


class Pipeline:
    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.ba = BusinessAnalyst()
        self.ea = EnterpriseArchitect()
        self.sa = SolutionArchitect()
        self.dev = Developer()
        self.po = ProcessOrganiser()
        self.tsw = TestScriptWriter()
        self.tester = Tester()
        self.bugfixer = BugFixer()

    async def run(self, requirement: str) -> PipelineResult:
        feature_id = next_feature_id()
        started = now_iso()
        t0 = time.perf_counter()
        artifact_paths: dict[str, str] = {}
        ea_post_decision = "skipped"
        bug_fix_iterations = 0
        status = "completed"
        halt_reason: str | None = None
        final_defect_count = 0

        print(f"▸ Pipeline start: {feature_id} — {requirement[:80]}")
        print(f"  Started: {started}")

        try:
            # 1. Business Analyst
            print("▸ BA → RTM + BPDD ...", flush=True)
            ba_out = await self.ba.run(
                feature_id=feature_id,
                payload=BARequest(requirement=requirement),
            )
            artifact_paths["ba"] = relative_to_repo(_latest_artifact("ba", feature_id))
            bpdd = ba_out.bpdd
            print(
                f"  ✅ {len(ba_out.rtm.rows)} reqs, domain={bpdd.domain}, sub={bpdd.sub_section}"
            )

            # 2. EA pre-build
            print("▸ EA pre-build review ...", flush=True)
            ea_pre = await self.ea.run(
                feature_id=feature_id,
                payload=EARequest(stage="pre_build", bpdd=bpdd),
                suffix="pre",
            )
            artifact_paths["ea_pre"] = relative_to_repo(
                _latest_artifact("ea", feature_id, suffix="pre")
            )
            print(f"  ✅ {ea_pre.decision}")
            if ea_pre.decision == "rejected":
                return self._halt(
                    feature_id,
                    requirement,
                    started,
                    t0,
                    artifact_paths,
                    "ea_pre_rejected",
                    ", ".join(ea_pre.misalignments),
                )

            # 3. Solution Architect
            print("▸ SA → SDD ...", flush=True)
            sdd = await self.sa.run(feature_id=feature_id, payload=SARequest(bpdd=bpdd))
            artifact_paths["sa"] = relative_to_repo(_latest_artifact("sa", feature_id))
            print(
                f"  ✅ {len(sdd.components)} components, {len(sdd.apis)} apis, "
                f"{len(sdd.data_models)} models"
            )

            # 4. Developer
            print("▸ Developer → FeatureCode ...", flush=True)
            code: FeatureCode = await self.dev.run(
                feature_id=feature_id, payload=DevRequest(sdd=sdd)
            )
            artifact_paths["dev"] = relative_to_repo(
                _latest_artifact("dev", feature_id)
            )
            self._validate_paths(code)
            print(f"  ✅ {len(code.files)} files generated")

            # 5. Process Organiser
            print("▸ Process Organiser → PHD update ...", flush=True)
            po_out = await self.po.run(
                feature_id=feature_id,
                payload=PORequest(
                    feature_id=feature_id,
                    feature_name=bpdd.feature_name,
                    domain=bpdd.domain,
                    sub_section=bpdd.sub_section,
                    added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            artifact_paths["po"] = relative_to_repo(_latest_artifact("po", feature_id))
            phd_path = update_phd(PHEntry(**po_out.entry.model_dump()))
            artifact_paths["phd"] = relative_to_repo(phd_path)
            print(f"  ✅ entry appended to {relative_to_repo(phd_path)}")

            # 6. Test Script Writer
            print("▸ TSW → test scripts ...", flush=True)
            scripts = await self.tsw.run(
                feature_id=feature_id, payload=TSWRequest(bpdd=bpdd, sdd=sdd)
            )
            artifact_paths["tsw"] = relative_to_repo(
                _latest_artifact("tsw", feature_id)
            )
            print(f"  ✅ {len(scripts.scripts)} test scripts")

            # 7. Tester (iter 0)
            print("▸ Tester (iter 0) ...", flush=True)
            catalogue: DefectCatalogue = await self.tester.run(
                feature_id=feature_id,
                payload=TesterRequest(scripts=scripts, code=code, iteration=0),
                suffix="run0",
            )
            print(f"  ✅ {len(catalogue.defects)} defects")

            # 8. Bug-fix loop
            while catalogue.defects:
                bug_fix_iterations += 1
                if bug_fix_iterations > MAX_ITERATIONS:
                    halt_reason = (
                        f"unresolved defects after {MAX_ITERATIONS} bug-fix iterations"
                    )
                    status = "halted"
                    print(f"  ⚠️  {halt_reason}")
                    break
                print(
                    f"▸ BugFixer (iter {bug_fix_iterations}) → fixing "
                    f"{len(catalogue.defects)} defects ...",
                    flush=True,
                )
                fix_out = await self.bugfixer.run(
                    feature_id=feature_id,
                    payload=BugFixRequest(
                        catalogue=catalogue, code=code, iteration=bug_fix_iterations
                    ),
                    suffix=f"iter{bug_fix_iterations}",
                )
                code = fix_out.fixed_code
                self._validate_paths(code)
                print(f"  ✅ {len(fix_out.fixes_applied)} fixes")

                print(f"▸ Tester (iter {bug_fix_iterations}) ...", flush=True)
                catalogue = await self.tester.run(
                    feature_id=feature_id,
                    payload=TesterRequest(
                        scripts=scripts, code=code, iteration=bug_fix_iterations
                    ),
                    suffix=f"run{bug_fix_iterations}",
                )
                print(f"  ✅ {len(catalogue.defects)} defects remaining")

            final_defect_count = len(catalogue.defects)

            # 9. EA post-build (always runs)
            print("▸ EA post-build review ...", flush=True)
            ea_post = await self.ea.run(
                feature_id=feature_id,
                payload=EARequest(stage="post_build", bpdd=bpdd, sdd=sdd, code=code),
                suffix="post",
            )
            artifact_paths["ea_post"] = relative_to_repo(
                _latest_artifact("ea", feature_id, suffix="post")
            )
            ea_post_decision = ea_post.decision
            print(f"  ✅ {ea_post.decision}")

            # Live-mode write + commit
            if not self.dry_run:
                branch_name = self._write_to_branch(feature_id, requirement, code)
                artifact_paths["branch"] = branch_name
                print(f"▸ Committed to branch: {branch_name}")

        except Exception as exc:  # noqa: BLE001
            status = "halted"
            halt_reason = f"{type(exc).__name__}: {exc}"
            _log.exception("Pipeline halted")
            print(f"  ❌ HALTED: {halt_reason}")

        duration = time.perf_counter() - t0
        log_pipeline_run_row(
            started=started,
            feature_id=feature_id,
            requirement=requirement,
            status=status,
            bug_fix_iterations=bug_fix_iterations,
            ea_post_decision=ea_post_decision,
            duration_seconds=duration,
        )
        print(f"▸ Pipeline {status} in {duration:.1f}s")

        return PipelineResult(
            feature_id=feature_id,
            requirement=requirement,
            status=status,
            halt_reason=halt_reason,
            bug_fix_iterations=bug_fix_iterations,
            final_defect_count=final_defect_count,
            duration_seconds=duration,
            artifact_paths=artifact_paths,
        )

    def _halt(
        self,
        feature_id: str,
        requirement: str,
        started: str,
        t0: float,
        artifact_paths: dict[str, str],
        reason_code: str,
        detail: str,
    ) -> PipelineResult:
        duration = time.perf_counter() - t0
        log_pipeline_run_row(
            started=started,
            feature_id=feature_id,
            requirement=requirement,
            status="halted",
            bug_fix_iterations=0,
            ea_post_decision="skipped",
            duration_seconds=duration,
        )
        print(f"  ❌ HALT: {reason_code} — {detail}")
        return PipelineResult(
            feature_id=feature_id,
            requirement=requirement,
            status="halted",
            halt_reason=f"{reason_code}: {detail}",
            duration_seconds=duration,
            artifact_paths=artifact_paths,
        )

    def _validate_paths(self, code: FeatureCode) -> None:
        for f in code.files:
            ok, reason = is_path_allowed(f.path)
            if not ok:
                raise RuntimeError(
                    f"Developer/BugFixer attempted forbidden path '{f.path}': {reason}"
                )

    def _write_to_branch(
        self, feature_id: str, requirement: str, code: FeatureCode
    ) -> str:
        slug = slug_from_requirement(requirement)
        branch = f"dev-team/{feature_id.lower()}-{slug}"
        root = repo_root()
        # Create branch from current HEAD
        _git(["checkout", "-b", branch], cwd=root)
        try:
            for f in code.files:
                target = root / f.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f.content)
            _git(["add", "."], cwd=root)
            _git(
                [
                    "commit",
                    "-m",
                    f"feat({feature_id}): {code.summary[:72]}\n\nGenerated by dev-team pipeline.\n\nFiles:\n"
                    + "\n".join(f"- {f.path}" for f in code.files),
                ],
                cwd=root,
            )
        finally:
            # Always switch back to whatever branch was active before
            pass
        return branch


def _git(args: list[str], *, cwd: Path) -> None:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {res.stderr.strip() or res.stdout.strip()}"
        )


def _latest_artifact(agent_dir: str, feature_id: str, *, suffix: str = "") -> Path:
    out_dir = repo_root() / "tasks" / "agent-outputs" / agent_dir
    if not out_dir.exists():
        return out_dir / f"{feature_id}_NOT_FOUND.json"
    needle = f"{feature_id}_{suffix}_" if suffix else f"{feature_id}_"
    matches = sorted(out_dir.glob(f"{needle}*.json"))
    return matches[-1] if matches else out_dir / f"{feature_id}_NOT_FOUND.json"
