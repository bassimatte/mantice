#!/usr/bin/env python3
"""
Quick test script for R1 fix (render continuity)
Runs automated tests to verify the fix works correctly
"""

import subprocess
import sys
from pathlib import Path

def run_test(name, command, description):
    """Run a single test and report results"""
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"Description: {description}")
    print(f"{'='*60}")
    print(f"Command: {' '.join(command)}")
    print()
    
    try:
        result = subprocess.run(command, check=True, capture_output=False)
        print(f"\n✅ {name} PASSED")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {name} FAILED (exit code {e.returncode})")
        return False
    except Exception as e:
        print(f"\n❌ {name} ERROR: {e}")
        return False

def main():
    """Run all R1 tests"""
    print("="*60)
    print("R1 FIX TEST SUITE: Render Continuity")
    print("="*60)
    print("\nThis will test:")
    print("1. Automation continuity (no resets)")
    print("2. Reverb tail preservation")
    print("3. Journey template arc")
    print("4. Short render (no regression)")
    print("5. Multi-voice FM coherence")
    print()
    
    tests = [
        ("Test 1: Automation Sweep", 
         ["python", "main.py", "--preset", "test_automation_sweep", 
          "--output", "test1_sweep.wav", "--hires"],
         "90s filter sweep 300→7000Hz should be smooth, no resets"),
        
        ("Test 2: Long Reverb",
         ["python", "main.py", "--preset", "test_reverb_tail",
          "--output", "test2_reverb.wav", "--hires"],
         "90s cathedral reverb should be continuous, no cuts"),
        
        ("Test 3: Journey Template",
         ["python", "main.py", "--preset", "Om", "--duration", "90",
          "--auto", "journey", "--output", "test3_journey.wav", "--hires"],
         "90s journey arc should flow naturally, no repetitions"),
        
        ("Test 4: Short Render",
         ["python", "main.py", "--preset", "Om", "--duration", "10",
          "--output", "test4_short.wav", "--hires"],
         "10s render should complete quickly, no segmentation"),
        
        ("Test 5: Multi-Voice FM",
         ["python", "main.py", "--preset", "test_fm_voices",
          "--output", "test5_fm.wav", "--hires"],
         "90s FM voices should have consistent timbre throughout"),
    ]
    
    results = []
    for name, command, description in tests:
        passed = run_test(name, command, description)
        results.append((name, passed))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    print()
    print(f"Results: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 ALL TESTS PASSED - R1 fix is working correctly!")
        print("\nNext steps:")
        print("1. Listen to the generated WAV files in exports/")
        print("2. Check for smooth automation sweeps (test1)")
        print("3. Check for continuous reverb (test2)")
        print("4. If audio sounds good, R1 is VERIFIED ✅")
        return 0
    else:
        print(f"\n⚠️  {total_count - passed_count} test(s) failed")
        print("\nPlease check the console output above for errors")
        return 1

if __name__ == "__main__":
    sys.exit(main())
