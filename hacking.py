import os
import torch
import torch.nn as nn
import random
import string
import tiktoken
import argparse
import yaml
from typing import List, Dict, Tuple, Any, Optional
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
from huggingface_hub import login
from words import words
from utils import (
    minimize_tokens,
    sample_control,
    count_tokens,
    get_random_words,
    token_gradients_combined,
    find_best_word_to_add,
    words_db,
    get_filtered_cands,
)
from dotenv import load_dotenv

# Load configuration from YAML file
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Extract configuration parameters
model_config = config["model"]
optimization_config = config["optimization"]
prefix_config = config["prefix"]
stagnation_config = config["stagnation"]
scoring_config = config["scoring"]
text_config = config["text"]

# check if cuda is available
use_gpu = model_config.get("use_gpu", torch.cuda.is_available())
cuda_available: bool = torch.cuda.is_available() and use_gpu
device: torch.device = torch.device("cuda" if cuda_available else "cpu")

# use token from environment variable
if model_config.get("load_hf_token_from_env", False):
    load_dotenv()

hf_token = os.getenv("HF_TOKEN")
if hf_token:
    login(token=hf_token)
else:
    login()

alpha: float = optimization_config["alpha"]
min_benign_confidence: float = optimization_config["min_benign_confidence"]
words_to_inject: int = prefix_config["words_to_inject"]
improvement_threshold: float = optimization_config["improvement_threshold"]
rolling_window_size: int = scoring_config["rolling_window_size"]

# Define a threshold for injecting educational text when optimization stagnates
stagnation_threshold: int = stagnation_config["threshold"]
grace_period: int = stagnation_config["grace_period"]
max_iterations: int = optimization_config["max_iterations"]
patience: int = optimization_config["patience"]
max_top_scores: int = scoring_config["max_top_scores"]
rolling_weight: float = scoring_config["rolling_weight"]
top_weight: float = scoring_config["top_weight"]

# Define token penalty weight - higher values penalize longer prefixes more
token_penalty_weight: float = optimization_config["token_penalty_weight"]
min_acceptable_benign: float = optimization_config["min_acceptable_benign"]

model_id: str = model_config["id"]
# model_id = "meta-llama/Llama-Prompt-Guard-2-22M"
tokenizer: AutoTokenizer = AutoTokenizer.from_pretrained(model_id)
model: AutoModelForSequenceClassification = AutoModelForSequenceClassification.from_pretrained(
    model_id
)
model = model.to(device)  # Move model to MPS device

benign_class: str = model_config["benign_class"]
malicious_class: str = model_config["malicious_class"]

# Find the class indices
benign_class_idx: Optional[int] = None
malicious_class_idx: Optional[int] = None

for idx, label in model.config.id2label.items():
    if label.lower() == benign_class:
        benign_class_idx = idx
    elif label.lower() == malicious_class:
        malicious_class_idx = idx

if benign_class_idx is None:
    benign_class_idx = 0  # Assuming binary classification with benign=1
if malicious_class_idx is None:
    malicious_class_idx = 1  # Assuming binary classification with malicious=0

injection_text = text_config["injection"]
text: str = text_config["mandatory"]

# Number of words to use in the initial prefix
init_prefix_words_count: int = prefix_config["init_words_count"]
# How much to prioritize token count vs improvement (higher = more focus on tokens)
init_token_priority: float = prefix_config["init_token_priority"]
general_token_priority: float = prefix_config["general_token_priority"]

# Try to use top-performing words from the database for the initial prefix
top_words = words_db.get_top_words(
    limit=init_prefix_words_count, min_uses=1, token_weight=init_token_priority
)
if top_words:
    print(f"Using {len(top_words)} top-performing words from database for initial prefix")
    # Get words with combined token and improvement prioritization
    initial_words = get_random_words(
        n=init_prefix_words_count,
        min_uses=1,  # Words must have been tested at least once
        token_priority=init_token_priority,
    )
    init_prefix: str = " ".join(initial_words)
    print(
        f"Created initial prefix using database-informed words (token priority: {init_token_priority})"
    )
else:
    # Fall back to random words if the database doesn't have enough data
    init_prefix: str = " ".join(words[:init_prefix_words_count])
    print(f"Using random words for initial prefix (no database history available)")

# init_prefix = "".join(random.choices(words, k=init_prefix_words_count))


def main():
    global injection_text, text, init_prefix_words_count
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Prompt hacking tool")
    parser.add_argument(
        "--injection",
        type=str,
        default=text_config["injection"],
        help="Injection text to use in the template",
    )
    parser.add_argument(
        "--mandatory-text",
        type=str,
        default=text_config["mandatory"],
        help="Mandatory text to use in the template",
    )
    parser.add_argument(
        "--init-prefix-words-count",
        type=int,
        default=prefix_config["init_words_count"],
        help="Number of words to use in the initial prefix",
    )

    args = parser.parse_args()

    # Update the global parameters based on command line arguments
    injection_text = args.injection
    text = args.mandatory_text
    init_prefix_words_count = args.init_prefix_words_count

    print(f"Injection text: {injection_text}")
    print(f"Mandatory text: {text}")

    print(f"\nTrying initial prefix: {init_prefix}")

    # Convert initial adversarial string to tokens
    best_score: float = float("-inf")
    best_prefix: Optional[str] = None
    adv_prefix: str = init_prefix
    adv_prefix_tokens: torch.Tensor = tokenizer(
        adv_prefix, return_tensors="pt", add_special_tokens=False
    )["input_ids"][0]
    adv_prefix_tokens = adv_prefix_tokens.to(device)  # Move tokens to MPS device
    control_slice: slice = slice(0, len(adv_prefix_tokens))  # Slice representing the prefix tokens

    best_iteration_score: float = float("-inf")
    iterations_without_improvement: int = 0
    found_high_confidence_benign: bool = False

    # Track both rolling and top scores
    rolling_scores: List[float] = []  # List to store recent scores
    top_scores: List[float] = []  # List to store top scores

    # Track token counts
    current_token_count: int = count_tokens(adv_prefix)
    min_token_count: int = current_token_count

    for i in range(max_iterations):
        # Prepare input tensors using template
        full_text = injection_text + adv_prefix + text
        inputs: Dict[str, torch.Tensor] = tokenizer(full_text, return_tensors="pt")
        input_ids: torch.Tensor = inputs["input_ids"][0].to(device)  # Move input_ids to MPS device

        # Compute gradients using combined approach
        coordinate_grad: torch.Tensor = token_gradients_combined(
            model,
            input_ids,
            control_slice,
            benign_class=benign_class_idx,
            malicious_class=malicious_class_idx,
            alpha=alpha,
            device=device,
        )

        # Ensure coordinate_grad is on the correct device and has the right shape
        coordinate_grad = coordinate_grad.to(device)

        # Generate and evaluate new candidates
        try:
            # Ensure adv_prefix_tokens is on the correct device
            adv_prefix_tokens = adv_prefix_tokens.to(device)

            # Sample new tokens with exploration parameters
            new_adv_prefix_toks: torch.Tensor = sample_control(
                adv_prefix_tokens,
                coordinate_grad,
                batch_size=32,  # Larger batch for more candidates
                topk=16,  # More options per token
                temp=1.5,  # Higher temperature for more exploration
            )

            # Convert new tokens to text
            new_adv_prefix: List[str] = get_filtered_cands(
                tokenizer,
                new_adv_prefix_toks,
                filter_cand=False,
                curr_control=adv_prefix,
            )

            # Batch evaluation for all candidates with combined scoring
            candidate_texts = [injection_text + cand + text for cand in new_adv_prefix]
            token_counts = [count_tokens(cand) for cand in new_adv_prefix]
            min_count = min(token_counts) if token_counts else 0
            max_count = max(token_counts) if token_counts else 1
            count_range = max(1, max_count - min_count)
            inputs = tokenizer(candidate_texts, return_tensors="pt", padding=True, truncation=True)
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                logits = model(**inputs).logits
                probs = torch.softmax(logits, dim=-1)
                benign_scores = probs[:, benign_class_idx].cpu().numpy()
                # Compute normalized loss for each candidate
                losses = nn.CrossEntropyLoss(reduction="none")(
                    logits,
                    torch.zeros(logits.shape[0], device=device, dtype=torch.long),
                )
                normalized_losses = 1.0 / (1.0 + losses.cpu().numpy())

            # Compute token penalty for each candidate
            token_penalties = [
                1.0 - ((tc - min_count) / count_range) if count_range > 0 else 0
                for tc in token_counts
            ]
            # Compute combined score for each candidate
            combined_scores = [
                (alpha * benign_scores[i] + (1 - alpha) * normalized_losses[i])
                * (1 - token_penalty_weight + token_penalty_weight * token_penalties[i])
                for i in range(len(new_adv_prefix))
            ]
            idx = int(max(range(len(combined_scores)), key=lambda i: combined_scores[i]))
            adv_prefix = new_adv_prefix[idx]

            # Update the tokens for the next iteration
            adv_prefix_tokens = tokenizer(
                adv_prefix, return_tensors="pt", add_special_tokens=False
            )["input_ids"][0]
            adv_prefix_tokens = adv_prefix_tokens.to(device)

            # Check the current classification
            full_text = injection_text + adv_prefix + text
            inputs: Dict[str, torch.Tensor] = tokenizer(full_text, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                logits: torch.Tensor = model(**inputs).logits
                probs: torch.Tensor = torch.softmax(logits, dim=-1)
                predicted_class_id: int = logits.argmax().item()
                benign_score: float = probs[0][benign_class_idx].item()
                benign_percentage: float = benign_score * 100
                malicious_score: float = (
                    probs[0][malicious_class_idx].item() if malicious_class_idx is not None else 0
                )

                # Calculate combined score
                loss: torch.Tensor = nn.CrossEntropyLoss()(
                    logits, torch.zeros(logits.shape[0], device=device).long()
                )
                normalized_loss: float = 1.0 / (1.0 + loss.item())
                current_score: float = alpha * benign_score + (1 - alpha) * normalized_loss

                # Update rolling average
                rolling_scores.append(current_score)
                if len(rolling_scores) > rolling_window_size:
                    rolling_scores.pop(0)  # Remove oldest score
                rolling_avg: float = sum(rolling_scores) / len(rolling_scores)

                # Update top scores
                top_scores.append(current_score)
                top_scores.sort(reverse=True)  # Sort in descending order
                if len(top_scores) > max_top_scores:
                    top_scores = top_scores[:max_top_scores]  # Keep only top N scores
                top_avg: float = sum(top_scores) / len(top_scores)

                # Calculate weighted combined average
                combined_avg: float = (rolling_weight * rolling_avg) + (top_weight * top_avg)

                # Count tokens in current prefix
                current_token_count = count_tokens(adv_prefix)
                if current_token_count < min_token_count:
                    min_token_count = current_token_count

                print(
                    f"Iteration {i+1}: Class={model.config.id2label[predicted_class_id]} "
                    + f"(benign: {benign_percentage:.2f}%, loss_norm: {normalized_loss:.4f}, "
                    + f"tokens: {current_token_count}, prefix: {adv_prefix})"
                )

                if current_score > best_iteration_score:
                    # New best score, reset counter
                    best_iteration_score = current_score
                    iterations_without_improvement = 0
                elif current_score >= combined_avg * improvement_threshold:
                    # Score is close enough to combined average, don't count against patience
                    print(
                        f"  Score within {(1-improvement_threshold)*100:.1f}% of combined average, continuing optimization"
                    )
                    # Don't increment iterations_without_improvement
                else:
                    # Score is significantly worse than combined average, count against patience
                    iterations_without_improvement += 1
                    print(
                        f"  No significant improvement for {iterations_without_improvement}/{patience} iterations"
                    )

                    # If we're stagnating but not yet at early stopping threshold, try injecting educational text
                    if (
                        iterations_without_improvement % stagnation_threshold == 0
                        and iterations_without_improvement < patience
                    ):
                        print(
                            f"\n  Optimization stagnating. Looking for words to improve benign rating..."
                        )

                        # Try to find the best word to add
                        new_prefix: Optional[str]
                        improvement: float
                        new_prefix, improvement = find_best_word_to_add(
                            model,
                            tokenizer,
                            injection_text,
                            adv_prefix,
                            text,
                            benign_class_idx,
                            device=device,
                            num_candidates=len(words),
                            token_priority=general_token_priority,  # Equal weight to token count and improvement
                        )

                        if new_prefix and improvement > 0:
                            # Use the optimized prefix with the best word added
                            adv_prefix = new_prefix
                            print(
                                f"  Applied optimized prefix with improvement of {improvement:.4f}"
                            )
                        else:
                            # Fall back to adding random words if no improvement found
                            snippet: str = " ".join(
                                get_random_words(
                                    words_to_inject,
                                    1,
                                    token_priority=general_token_priority,
                                )
                            )

                            # Insert the snippet at the beginning
                            adv_prefix = snippet + " " + adv_prefix
                            print(
                                f"  No improvement found, inserted random words at beginning: '{snippet}'"
                            )

                        # Update tokens for next iteration
                        adv_prefix_tokens = tokenizer(
                            adv_prefix, return_tensors="pt", add_special_tokens=False
                        )["input_ids"][0]
                        adv_prefix_tokens = adv_prefix_tokens.to(device)
                        control_slice = slice(0, len(adv_prefix_tokens))

                        # Give the model time to improve with the new text by resetting best score tracking
                        best_iteration_score = float("-inf")
                        iterations_without_improvement = max(
                            0, iterations_without_improvement - grace_period
                        )
                        print(f"  Reset optimization tracking to give new text time to work")

                # Early stopping check - only stop if consistently no improvement
                if iterations_without_improvement >= patience:
                    print(f"Early stopping after {i+1} iterations with no significant improvement")
                    break

                # Always track the best prefix we've seen, even if not high confidence
                if (
                    model.config.id2label[predicted_class_id].lower() == benign_class
                    and current_score > best_score
                ):
                    best_score = current_score
                    best_prefix = adv_prefix
                    print(
                        f"New best benign prefix found with score: {best_score:.4f}, benign confidence: {benign_percentage:.2f}%"
                    )

                # Check if we've found a high confidence benign classification (>95%)
                if (
                    model.config.id2label[predicted_class_id].lower() == benign_class
                    and benign_score > min_benign_confidence
                ):
                    found_high_confidence_benign = True  # Set the flag
                    best_score = current_score
                    best_prefix = adv_prefix
                    print(
                        f"Found high confidence benign classification ({benign_percentage:.2f}%) at iteration {i+1}! Stopping optimization."
                    )
                    break  # Stop optimizing

        except Exception as e:
            # print stack trace
            import traceback

            traceback.print_exc()
            print(f"Error in iteration {i+1}: {str(e)}")
            continue

    # Print final results
    if found_high_confidence_benign:
        print(
            f"\n===== SUCCESS! Found a high confidence benign classification (>{min_benign_confidence*100}%) ====="
        )

        # Now minimize the tokens while maintaining the benign classification
        if best_prefix is not None:
            best_prefix = minimize_tokens(
                model,
                tokenizer,
                injection_text,
                best_prefix,
                text,
                benign_class_idx,
                device=device,
                min_acceptable_benign=min_acceptable_benign,
            )
    else:
        print("\n===== Did not find a high confidence benign classification =====")
        if best_prefix is not None:
            print(f"Best prefix found had a benign score of: {best_score:.4f}")

            # Still try to minimize tokens
            best_prefix = minimize_tokens(
                model,
                tokenizer,
                injection_text,
                best_prefix,
                text,
                benign_class_idx,
                device=device,
                min_acceptable_benign=min_acceptable_benign,
            )

    # Use the best prefix found across all runs
    adv_prefix: str = best_prefix if best_prefix is not None else init_prefix

    # Without adversarial prefix
    inputs: Dict[str, torch.Tensor] = tokenizer(text, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}  # Move inputs to MPS device
    logits: torch.Tensor = model(**inputs).logits
    probs: torch.Tensor = torch.softmax(logits, dim=-1)
    predicted_class_id: int = logits.argmax().item()
    benign_prob: float = probs[0][benign_class_idx].item() * 100
    print(f"\nPayload is: {text}")
    print(
        f"Payload without prefix is classified as: {model.config.id2label[predicted_class_id]} (benign probability: {benign_prob:.2f}%)"
    )

    # With adversarial prefix
    full_text = injection_text + adv_prefix + text
    inputs = tokenizer(full_text, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}  # Move inputs to MPS device
    logits = model(**inputs).logits
    probs = torch.softmax(logits, dim=-1)
    predicted_class_id = logits.argmax().item()
    benign_prob = probs[0][benign_class_idx].item() * 100
    print(f"Prefix is: {adv_prefix}")
    print(f"Complete text using template is: {full_text}")
    print(f"COPY THIS:\n --- \n{injection_text+adv_prefix}\n --- \n")
    print(
        f"Payload with prefix is classified as: {model.config.id2label[predicted_class_id]} (benign probability: {benign_prob:.2f}%)"
    )

    # Try to run inference with the model's classifier
    classifier = pipeline(
        "text-classification",
        model=model_id,
        device=0 if cuda_available else -1,
    )

    try:
        # Test with original text
        result_original: List[Dict[str, Any]] = classifier(text)
        print(f"\nClassifier result (original text): {result_original}")

        # Test with prefix + text
        result_with_prefix: List[Dict[str, Any]] = classifier(full_text)
        print(f"Classifier result (with template): {result_with_prefix}")
    except Exception as e:
        print(f"Error running classifier pipeline: {str(e)}")

    print(f"Adv prefix token count: {count_tokens(adv_prefix)}")
    print(f"Total token count: {count_tokens(full_text)}")


if __name__ == "__main__":
    main()
