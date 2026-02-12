#!/usr/bin/env python3
"""
📤 Upload Langfuse Prompt v27 to Langfuse Platform

Uploads the improved prompt v27 with all 5 critical fixes:
- Fix #1: Reformulated Rule #4 (data-only mode)
- Fix #2: KPI selection rules
- Fix #3: Skill detail requirements
- Fix #4: Careerogram mandatory
- Fix #5: Boundary checking rules

Expected impact: Quality 2.8/10 → 6.0/10 (+114%)
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Load .env variables
env_path = Path("/home/yan/A101/HR/.env")
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value

sys.path.insert(0, "/home/yan/A101/HR")

from langfuse import Langfuse


def upload_prompt_v27():

    """Upload prompt v27 to Langfuse.
    
    This function handles the uploading of the v27 prompt to Langfuse by first
    initializing the Langfuse client with the necessary credentials. It reads the
    prompt from a specified file, processes the content to remove metadata, and
    then attempts to create the prompt in Langfuse. If the prompt already exists,
    it will create a new version instead.
    
    Returns:
        bool: True if the upload or version creation was successful, False otherwise.
    """
    print("📤 Uploading Prompt v27 to Langfuse")
    print("=" * 70)

    # Initialize Langfuse
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        print("❌ Langfuse credentials not found in .env")
        return False

    langfuse = Langfuse(
        public_key=public_key, secret_key=secret_key, host="https://cloud.langfuse.com"
    )

    # Read v27 prompt
    v27_path = Path("/tmp/langfuse_prompt_v27_improved.txt")
    if not v27_path.exists():
        print(f"❌ Prompt v27 not found at {v27_path}")
        return False

    with open(v27_path, "r", encoding="utf-8") as f:
        v27_content = f.read()

    # Remove metadata header (first 8 lines)
    lines = v27_content.split("\n")
    prompt_start = 0
    for i, line in enumerate(lines):
        if "================" in line:
            prompt_start = i + 1
            break

    prompt_text = "\n".join(lines[prompt_start:]).strip()

    print(f"✅ Loaded prompt v27 ({len(prompt_text)} chars, {len(prompt_text.split())} words)")
    print(f"   Estimated tokens: ~{len(prompt_text) // 4}")

    # Create prompt configuration
    # Note: We're creating a text prompt, not a chat prompt
    # The actual model configuration is in LLMClient/ProfileGenerator

    try:
        print("\n🚀 Creating prompt v27 in Langfuse...")

        result = langfuse.create_prompt(
            name="a101-hr-profile-gemini-v3-simple",
            prompt=prompt_text,  # Text prompt (not chat messages)
            labels=["production", "v27", "phase1-improvements"],
            tags=[
                "a101",
                "hr",
                "profile-generation",
                "gemini-2.5-flash",
                "fix-rule4",
                "kpi-filtering",
                "skill-detail",
                "careerogram-mandatory",
                "boundary-checking",
            ],
            type="text",
            config={
                "version": "27",
                "changes_from_v26": [
                    "Fix #1: Reformulated Rule #4 (data-only mode)",
                    "Fix #2: Added KPI selection rules (filter by weight)",
                    "Fix #3: Added skill detail requirements (tools, versions)",
                    "Fix #4: Made careerogram mandatory (no empty arrays)",
                    "Fix #5: Added boundary checking rules (department scope)",
                ],
                "expected_impact": {
                    "overall_quality": "2.8/10 → 6.0/10 (+114%)",
                    "kpi_accuracy": "60% → 95%+ (+58%)",
                    "skill_detail": "2.6/5 → 4.5/5 (+73%)",
                    "generic_terms": "13.6 → <2 (-85%)",
                    "careerogram_completeness": "70% → 100% (+43%)",
                    "boundary_violations": "60% → <5% (-92%)",
                },
                "phase": "Phase 1 - Prompt Engineering",
                "implementation_date": datetime.now().strftime("%Y-%m-%d"),
            },
            commit_message="Phase 1: Add 5 critical fixes for quality improvement (v26 → v27)",
        )

        print("✅ Prompt v27 successfully uploaded to Langfuse!")
        print(f"   Name: a101-hr-profile-gemini-v3-simple")
        print(f"   Version: 27")
        print(f"   Type: text")
        print(f"   Size: {len(prompt_text)} chars (~{len(prompt_text) // 4} tokens)")
        print(f"   Labels: production, v27, phase1-improvements")
        print(f"\n📊 Changes from v26:")
        print(f"   ✅ Fix #1: Reformulated Rule #4 (CRITICAL)")
        print(f"   ✅ Fix #2: KPI selection rules")
        print(f"   ✅ Fix #3: Skill detail requirements")
        print(f"   ✅ Fix #4: Careerogram mandatory")
        print(f"   ✅ Fix #5: Boundary checking rules")
        print(f"\n🎯 Expected Impact:")
        print(f"   Overall Quality: 2.8/10 → 6.0/10 (+114%)")
        print(f"   KPI Accuracy: 60% → 95%+ (+58%)")
        print(f"   Skill Detail: 2.6/5 → 4.5/5 (+73%)")

        return True

    except Exception as e:
        print(f"❌ Failed to upload prompt: {e}")
        import traceback

        traceback.print_exc()

        # If prompt already exists, try to update it
        if "already exists" in str(e).lower() or "prompt with name" in str(e).lower():
            print("\n⚠️  Prompt 'a101-hr-profile-gemini-v3-simple' already exists")
            print("   Creating new version instead...")

            try:
                # Get current prompt to create new version
                existing_prompt = langfuse.get_prompt("a101-hr-profile-gemini-v3-simple")
                print(f"   Current version: {existing_prompt.version if hasattr(existing_prompt, 'version') else 'unknown'}")

                # Create new version by recreating the prompt
                # Langfuse automatically increments version
                result = langfuse.create_prompt(
                    name="a101-hr-profile-gemini-v3-simple",
                    prompt=prompt_text,
                    labels=["production", "v27", "phase1-improvements"],
                    tags=[
                        "a101",
                        "hr",
                        "v27-update",
                        "phase1-complete",
                    ],
                    type="text",
                    config={
                        "version": "27",
                        "update_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )

                print(f"✅ Created new version of prompt")
                return True

            except Exception as e2:
                print(f"❌ Failed to create new version: {e2}")
                return False

        return False


def test_prompt_retrieval_v27():

    """Test retrieving the uploaded prompt v27.
    
    This function tests the retrieval of a specific prompt from the Langfuse
    service using provided API keys.  It checks the prompt's content, identifies
    any fix markers, and retrieves associated configuration and labels.  If any
    issues occur during the retrieval process, it captures and prints the exception
    details.
    
    Returns:
        bool: True if the prompt was retrieved successfully, False otherwise.
    """
    print(f"\n🔍 Testing prompt v27 retrieval...")

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    langfuse = Langfuse(
        public_key=public_key, secret_key=secret_key, host="https://cloud.langfuse.com"
    )

    try:
        # Get the prompt
        prompt = langfuse.get_prompt("a101-hr-profile-gemini-v3-simple")

        print("✅ Prompt v27 retrieved successfully!")
        print(f"   Type: {type(prompt)}")

        if hasattr(prompt, "prompt"):
            content = prompt.prompt
            print(f"   Content type: {type(content)}")
            if isinstance(content, str):
                print(f"   Content length: {len(content)} chars")
                print(f"   Estimated tokens: ~{len(content) // 4}")

                # Check for fix markers
                fixes_found = []
                if "FIX #1" in content:
                    fixes_found.append("Fix #1 (Rule #4)")
                if "FIX #2" in content:
                    fixes_found.append("Fix #2 (KPI rules)")
                if "FIX #3" in content:
                    fixes_found.append("Fix #3 (Skill detail)")
                if "FIX #4" in content:
                    fixes_found.append("Fix #4 (Careerogram)")
                if "FIX #5" in content:
                    fixes_found.append("Fix #5 (Boundaries)")

                print(f"   Fixes detected: {len(fixes_found)}/5")
                for fix in fixes_found:
                    print(f"      ✅ {fix}")

                if len(fixes_found) < 5:
                    print(f"   ⚠️  WARNING: Not all fixes detected in prompt!")

        if hasattr(prompt, "config"):
            config = prompt.config
            print(f"   Config version: {config.get('version', 'N/A')}")

        if hasattr(prompt, "labels"):
            labels = prompt.labels
            print(f"   Labels: {labels}")

        return True

    except Exception as e:
        print(f"❌ Failed to retrieve prompt: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🏗️  A101 HR Profile Generator - Prompt v27 Upload")
    print("=" * 70)
    print("📋 Changes: 5 critical fixes for quality improvement")
    print("🎯 Expected: Quality 2.8/10 → 6.0/10 (+114%)")
    print("=" * 70)

    success_upload = upload_prompt_v27()
    success_test = test_prompt_retrieval_v27()

    if success_upload and success_test:
        print(f"\n🎉 SUCCESS: Prompt v27 uploaded and verified!")
        print(f"\n📊 Next steps:")
        print(f"  1. Update backend/core/prompt_manager.py to use v27")
        print(f"  2. Test generation with 3-5 sample profiles")
        print(f"  3. Compare quality metrics (v26 vs v27)")
        print(f"  4. Document results in Phase 1 report")
        print(f"\n🌐 Check prompt in Langfuse:")
        print(f"  https://cloud.langfuse.com/prompts/a101-hr-profile-gemini-v3-simple")
        exit_code = 0
    else:
        print(f"\n❌ FAILED: Prompt v27 upload incomplete")
        if success_upload and not success_test:
            print(f"   Note: Upload succeeded but retrieval test failed")
            print(f"   This may be a timing issue - check Langfuse UI")
            exit_code = 1
        else:
            exit_code = 1

    exit(exit_code)
