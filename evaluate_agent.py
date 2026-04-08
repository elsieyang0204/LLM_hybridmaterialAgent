import argparse
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding='utf-8')

from main_agent import build_graph, neo4j_tool

def evaluate_first_try_pass_rate(num_runs=20, query="Recommend broadband white-light copper halide candidates"):
    print(f"\n--- Running First-Try Pass Rate Evaluation ({num_runs} runs) ---")
    pass_count = 0
    total_valid = 0
    
    app = build_graph()
    
    def run_single(_):
        try:
            result = app.invoke({"user_query": query})
            retry_count = int(result.get("retry_count", 0) or 0)
            is_first_try = retry_count == 0
            final_success = bool(result.get("final_answer"))
            return is_first_try, final_success
        except Exception as e:
            return False, False
            
    # Run sequentially or mildly parallel to avoid rate limits
    results = []
    for i in range(num_runs):
        print(f"Run {i+1}/{num_runs}...", end=" ", flush=True)
        is_first_try, is_final_success = run_single(i)
        results.append((is_first_try, is_final_success))
        if is_first_try:
            print("Passed on 1st try.")
            pass_count += 1
        else:
            print("Failed 1st try.")
        if is_final_success:
            total_valid += 1
        time.sleep(2) # Reduce API rate limiting issues
        
    pass_rate = (pass_count / num_runs) * 100
    print(f"\n[Result] First-try pass rate: {pass_rate:.1f}%")
    print(f"[Result] Total successful outputs after loop-back: {(total_valid / num_runs) * 100:.1f}%")
    return pass_rate


def evaluate_consistency(num_runs=5, query='寻找适合做白光LED的高效铜基卤化物'):
    print(f"\n--- Running Consistency Evaluation ({num_runs} runs) ---")
    app = build_graph()

    top3_lists = []

    for i in range(num_runs):
        print(f"Run {i+1}/{num_runs}...", flush=True)
        try:
            result = app.invoke({"user_query": query})
            
            # The prompt requires tracking the Top-3 In-KG materials
            # These are retrieved by the retriever node and stored in 'candidates'
            candidates = result.get("candidates", [])
            formulas = [c.get("formula") for c in candidates[:3] if c.get("formula")]

            top3_lists.append(set(formulas))
            print(f"Top 3 In-KG formulas found: {formulas}")
            
        except Exception as e:
            print(f"Error in run {i+1}: {e}")
            top3_lists.append(set())
        
        time.sleep(2)

    # Calculate average overlap (Jaccard similarity between all pairs)
    overlaps = []
    num_sets = len(top3_lists)
    if num_sets > 1:
        for i in range(num_sets):
            for j in range(i + 1, num_sets):
                s1 = top3_lists[i]
                s2 = top3_lists[j]
                if not s1 and not s2: continue
                # Calculate Jaccard Similarity properly for consistency tracking
                intersection_size = len(s1.intersection(s2))
                union_size = len(s1.union(s2))
                overlap = intersection_size / union_size if union_size > 0 else 0.0
                overlaps.append(overlap)

    avg_overlap = (sum(overlaps) / len(overlaps) * 100) if overlaps else 0.0
    print(f"\n[Result] Average Top-3 Overlap Rate (Jaccard Similarity): {avg_overlap:.1f}%")
    return avg_overlap

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-try-runs", type=int, default=20)
    parser.add_argument("--consistency-runs", type=int, default=5)
    args = parser.parse_args()

    try:
        pass_rate = evaluate_first_try_pass_rate(num_runs=args.first_try_runs)
        consistency = evaluate_consistency(num_runs=args.consistency_runs)
        print(f"\n================ EVALUATION SUMMARY ================")
        print(f"First-Try Pass Rate = {pass_rate:.1f}%")
        print(f"Top-3 Overlap (Consistency) = {consistency:.1f}%")
        print("====================================================")
    finally:
        neo4j_tool.close()
