# Load Balancing & Fallback Models

This guide explains how to configure and use load balancing and fallback models in the LiteLLM proxy server. These features ensure high availability, optimal performance, and automatic failover when models are unavailable or rate-limited.

---

## Load Balancing

Load balancing distributes requests across multiple deployments of the same model to:

- `Maximize throughput` by utilizing multiple API keys/deployments
- `Avoid rate limits` by spreading load across different endpoints
- `Improve reliability` by having redundant deployments
- `Optimize costs` by routing to the most available deployment

---

**Supported Strategies**

**1. Usage-Based Routing v2 (Recommended)**

Routes requests based on real-time TPM (Tokens Per Minute) and RPM (Requests Per Minute) availability.

```yaml
router_settings:
  routing_strategy: "usage-based-routing-v2"
  enable_pre_call_checks: true
```

**How it works:**

- Tracks token and request usage in real-time
- Routes to deployment with most available capacity
- Prevents hitting rate limits before they occur
- Automatically updates based on actual usage

**2. Simple Shuffle**

Randomly distributes requests across available deployments.

```yaml
router_settings:
  routing_strategy: "simple-shuffle"
```

!!! Info "Use case"
    Equal load distribution without capacity tracking

**3. Latency-Based Routing**

Routes to the fastest responding deployment.

```yaml
router_settings:
  routing_strategy: "latency-based-routing"
```

!!! Info "Use case"
    Minimize response time for latency-sensitive applications

**4. Least Busy**

Routes to the deployment handling the fewest requests.

```yaml
router_settings:
  routing_strategy: "least-busy"
```

!!! Info "Use case" 
    Prevent overloading individual deployments

---

**Load Balancing Configuration**

```yaml
model_list:
  # Multiple deployments of the same model for load balancing
  - model_name: gpt-4o  # Same model name
    litellm_params:
      model: azure/gpt-4o-2  # Different deployment
      api_base: https://openai-248.openai.azure.com/
      api_key: YOUR_KEY_1
      client: azure
    model_info:
      tpm: 1200000  # Tokens per minute limit
      rpm: 500      # Requests per minute limit
      
  - model_name: gpt-4o  # Same model name
    litellm_params:
      model: azure/gpt-4o-3  # Different deployment
      api_base: https://openai-248.openai.azure.com/
      api_key: YOUR_KEY_2
      client: azure
    model_info:
      tpm: 916000
      rpm: 500
      
  - model_name: gpt-4o  # Same model name
    litellm_params:
      model: azure/gpt-4o-4  # Different deployment
      api_base: https://openai-248.openai.azure.com/
      api_key: YOUR_KEY_3
      client: azure
    model_info:
      tpm: 977000
      rpm: 500

router_settings:
  routing_strategy: "usage-based-routing-v2"
  num_retries: 3
  enable_pre_call_checks: true  # Check TPM/RPM before routing
  cooldown_time: 60  # Cooldown period after rate limit (seconds)
```

**Key Points:**

- Use same `model_name` for all deployments you want to load balance
- Use different deployment names in `litellm_params.model`
- Specify accurate TPM/RPM limits for optimal routing
- Enable pre_call_checks to prevent rate limit errors

**How Requests Are Routed**

```
Client Request: "gpt-4o"
         ↓
    Router checks:
    - Which gpt-4o deployments are available?
    - Which has most available TPM/RPM?
    - Any deployments in cooldown?
         ↓
    Routes to: azure/gpt-4o-3 (most available capacity)
         ↓
    If rate limited → Cooldown 60s → Try azure/gpt-4o-2
```

---

## Fallback Models

Fallback models are alternative models used when the primary model:

- Is rate-limited
- Times out
- Returns an error
- Is temporarily unavailable

**1. Model-Specific Fallbacks**

Define fallbacks for specific models:

```yaml
litellm_settings:
  fallbacks:
    - {gpt-5-chat: [gpt-4o]}          # gpt-5-chat → gpt-4o
    - {gpt-5-mini: [gpt-4o]}          # gpt-5-mini → gpt-4o
    - {gpt-5-nano: [gpt-5-mini, gpt-4o]}  # gpt-5-nano → gpt-5-mini → gpt-4o
    - {gpt-35-turbo: [gpt-4o]}        # gpt-35-turbo → gpt-4o
```

**Fallback Chain:**
```
Request: gpt-5-nano
    ↓
Try: gpt-5-nano (failed)
    ↓
Try: gpt-5-mini (failed)
    ↓
Try: gpt-4o (success) ✓
```

**2. Context Window Fallbacks**

Automatically fallback when context is too large:

```yaml
litellm_settings:
  context_window_fallbacks:
    - {gpt-4o: [gpt-5-chat]}  # If gpt-4o context exceeded → use gpt-5-chat
```

!!! Info "Use case"
    Request with 200K tokens → gpt-4o (128K limit) → gpt-5-chat (256K limit)

**3. Default Fallbacks**

Fallback for models without specific configuration:

```yaml
litellm_settings:
  default_fallbacks: [gpt-4o]  # Any undefined model → gpt-4o
```

!!! IMPORTANT
    The default fallback model should have **HIGH RATE LIMITS** (high TPM/RPM) since it will handle overflow traffic from all other models. Choose a model with the highest quota or multiple load-balanced deployments to prevent it from becoming a bottleneck.

**Recommended Default Fallback Configuration:**

```yaml
# GOOD: Default fallback with high limits and load balancing
model_list:
  - model_name: gpt-4o  # Default fallback
    litellm_params:
      model: azure/gpt-4o-2
      api_key: KEY_1
    model_info:
      tpm: 1200000  # High limit
      rpm: 500
      
  - model_name: gpt-4o  # Load balanced
    litellm_params:
      model: azure/gpt-4o-3
      api_key: KEY_2
    model_info:
      tpm: 916000
      rpm: 500
      
  - model_name: gpt-4o  # Load balanced
    litellm_params:
      model: azure/gpt-4o-4
      api_key: KEY_3
    model_info:
      tpm: 977000
      rpm: 500

litellm_settings:
  default_fallbacks: [gpt-4o]  # Uses load-balanced gpt-4o with 3M+ total TPM
```

```yaml
# BAD: Low-limit model as default fallback
litellm_settings:
  default_fallbacks: [gpt-5-nano]  # Only 100K TPM - will bottleneck!
```

**Retry Policy Configuration**

Control which errors trigger fallbacks:

```yaml
router_settings:
  retry_policy:
    ContentPolicyViolationErrorRetries: 0  # Never retry content violations
    BadRequestErrorRetries: 0              # Never retry bad requests
    TimeoutErrorRetries: 3                 # Retry timeouts 3 times
    InternalServerErrorRetries: 3          # Retry server errors 3 times
    RateLimitErrorRetries: 3               # Retry rate limits 3 times
```

**Allowed Fails Configuration**

Set how many failures before moving to fallback:

```yaml
router_settings:
  allowed_fails_policy:
    ContentPolicyViolationErrorAllowedFails: 0  # Fail immediately
  allowed_fails: 0  # Default for other errors
  cooldown_time: 60  # Cooldown after rate limit
```

---

## Configuration Examples

??? Example "Example 1: High-Availability Setup"

    **Goal:** Maximum uptime with automatic failover

    ```yaml
    model_list:
      # Primary: 3x gpt-4o deployments (load balanced)
      - model_name: gpt-4o
        litellm_params:
          model: azure/gpt-4o-2
          api_base: https://openai-248.openai.azure.com/
          api_key: KEY_1
          client: azure
        model_info:
          tpm: 1200000
          rpm: 500
          
      - model_name: gpt-4o
        litellm_params:
          model: azure/gpt-4o-3
          api_base: https://openai-248.openai.azure.com/
          api_key: KEY_2
          client: azure
        model_info:
          tpm: 916000
          rpm: 500
          
      - model_name: gpt-4o
        litellm_params:
          model: azure/gpt-4o-4
          api_base: https://openai-248.openai.azure.com/
          api_key: KEY_3
          client: azure
        model_info:
          tpm: 977000
          rpm: 500
      
      # Fallback: gpt-5-mini (cheaper, faster)
      - model_name: gpt-5-mini
        litellm_params:
          model: azure/gpt-5-mini
          api_base: https://sohan-mbtd9z9j-eastus2.openai.azure.com/
          api_key: KEY_4
          client: azure
        model_info:
          tpm: 120000
          rpm: 500

    litellm_settings:
      fallbacks:
        - {gpt-4o: [gpt-5-mini]}  # If all gpt-4o deployments fail → gpt-5-mini
      default_fallbacks: [gpt-4o]  # High TPM with load balancing

    router_settings:
      routing_strategy: "usage-based-routing-v2"
      num_retries: 3
      enable_pre_call_checks: true
      cooldown_time: 60
    ```

    **Request Flow:**
    ```
    1. Request gpt-4o
    2. Router tries: gpt-4o-2 (most available TPM)
    3. If rate limited → tries gpt-4o-3
    4. If rate limited → tries gpt-4o-4
    5. If all fail → fallback to gpt-5-mini
    ```

??? Example "Example 2: Cost-Optimized Setup"

    **Goal:** Use cheaper models first, expensive models as backup

    ```yaml
    model_list:
      # Primary: gpt-5-nano (cheapest)
      - model_name: gpt-5-nano
        litellm_params:
          model: azure/gpt-5-nano
          api_base: https://sohan-mbtd9z9j-eastus2.openai.azure.com/
          api_key: KEY_1
          client: azure
        model_info:
          tpm: 100000
          rpm: 500
      
      # Fallback 1: gpt-5-mini (moderate cost)
      - model_name: gpt-5-mini
        litellm_params:
          model: azure/gpt-5-mini
          api_base: https://sohan-mbtd9z9j-eastus2.openai.azure.com/
          api_key: KEY_2
          client: azure
        model_info:
          tpm: 120000
          rpm: 500
      
      # Fallback 2: gpt-4o (expensive, reliable, HIGH LIMIT)
      - model_name: gpt-4o
        litellm_params:
          model: azure/gpt-4o-2
          api_base: https://openai-248.openai.azure.com/
          api_key: KEY_3
          client: azure
        model_info:
          tpm: 1200000  # ✅ High limit for default fallback
          rpm: 500

    litellm_settings:
      fallbacks:
        - {gpt-5-nano: [gpt-5-mini, gpt-4o]}  # nano → mini → gpt-4o
      default_fallbacks: [gpt-4o]  # ✅ High-limit model as default
    ```

??? Example "Example 3: Performance-Optimized Setup"

    **Goal:** Minimize latency, maximize speed

    ```yaml
    router_settings:
      routing_strategy: "latency-based-routing"  # Route to fastest deployment
      num_retries: 1  # Fast fail
      enable_pre_call_checks: false  # Skip checks for speed
      cooldown_time: 30  # Shorter cooldown

    litellm_settings:
      fallbacks:
        - {gpt-5-chat: [gpt-5-mini]}  # Smaller model if needed
      default_fallbacks: [gpt-4o]  # ✅ Reliable high-limit fallback
      drop_params: true  # Drop unsupported params instead of failing
    ```

---

## Best Practices

**1. Load Balancing Best Practices**

**DO:**

- Use 2-4 deployments per model for optimal balance
- Set accurate TPM/RPM limits based on Azure quotas
- Enable `enable_pre_call_checks` to prevent rate limits
- Monitor usage patterns and adjust capacities
- Use `usage-based-routing-v2` for production

**DON'T:**

- Use more than 5 deployments (diminishing returns)
- Set TPM/RPM limits higher than actual quotas
- Mix different model versions under same model name
- Disable retries in production

**2. Fallback Best Practices**

**DO:**

- Choose fallback models with similar capabilities
- Use cheaper models as fallbacks when appropriate
- Set reasonable retry counts (2-3)
- Define context_window_fallbacks for large requests
- Test fallback chains before production
- `CRITICAL:` Ensure default fallback has HIGH rate limits
- Use load-balanced models as default fallbacks

**DON'T:**

- Create circular fallbacks (A → B → A)
- Use drastically different models as fallbacks
- Set ContentPolicyViolationErrorRetries > 0
- Have more than 3 levels in fallback chain
- Use low-limit models as default fallback
- Use single-deployment models with low TPM as default

**3. Default Fallback Selection Guide**

| Scenario | Recommended Default Fallback | Reason |
|----------|------------------------------|--------|
| `High Traffic` | Load-balanced gpt-4o (3+ deployments) | Handles overflow from all models |
| `Medium Traffic` | Single gpt-4o with high TPM | Sufficient capacity for occasional fallback |
| `Low Traffic` | gpt-5-mini (if high TPM available) | Cost-effective for low usage |
| `Cost-Sensitive` | gpt-4o with moderate TPM | Balance between cost and reliability |

??? Example "Example Capacity Planning"

    ```yaml
    # Total expected traffic: 500K TPM
    # Primary models: 300K TPM capacity
    # Default fallback should handle: 200K+ TPM overflow

    # GOOD: 3x gpt-4o = 3M TPM total capacity
    default_fallbacks: [gpt-4o]  # With 3 load-balanced deployments

    # BAD: 1x gpt-5-nano = 100K TPM (insufficient)
    default_fallbacks: [gpt-5-nano]  # Will bottleneck at 100K TPM
    ```

**4. Cooldown Configuration**

```yaml
router_settings:
  cooldown_time: 60  # Recommended: 60-120 seconds
```

**Guidelines:**

- `30s:` High traffic, quick recovery needed
- `60s:` Standard production use (recommended)
- `120s:` Conservative, prevent repeated failures
- `300s+:` Very conservative, long-running errors

**5. Monitoring Configuration**

```yaml
general_settings:
  store_model_in_db: true  # Enable for tracking
  disable_spend_logs: false  # Track costs

litellm_settings:
  logging: true  # Enable detailed logs
```

---

## Monitoring & Troubleshooting

**Check Router Status**

```bash
# Check health
curl http://localhost:4000/health

# Response includes:
{
  "status": "healthy",
  "models_available": ["gpt-4o", "gpt-5-chat", ...],
  "load_balancing": "enabled"
}
```

**View Model Statistics**

```bash
# Get model usage stats (if implemented)
curl http://localhost:4000/model/info
```

**Common Issues & Solutions**

**Issue 1: All Deployments Rate Limited**

**Symptoms:**
```
Error: All models exhausted. Rate limit exceeded on all deployments.
```

**Solutions:**
1. Add more deployments:
   ```yaml
   - model_name: gpt-4o
     litellm_params:
       model: azure/gpt-4o-5  # Add 5th deployment
   ```

2. Increase cooldown time:
   ```yaml
   router_settings:
     cooldown_time: 120  # Give more recovery time
   ```

3. Add fallback models:
   ```yaml
   litellm_settings:
     fallbacks:
       - {gpt-4o: [gpt-5-mini, gpt-5-nano]}
   ```

**Issue 2: Fallback Not Working**

**Symptoms:**
```
Error: Model failed, no fallback attempted
```

**Check:**
1. Fallback model is configured:
   ```yaml
   litellm_settings:
     fallbacks:
       - {gpt-5-chat: [gpt-4o]}  # Must be defined
   ```

2. Retry policy allows retries:
   ```yaml
   router_settings:
     retry_policy:
       RateLimitErrorRetries: 3  # Must be > 0
   ```

3. Fallback model exists in model_list:
   ```yaml
   model_list:
     - model_name: gpt-4o  # Fallback model must exist
   ```

**Issue 3: Uneven Load Distribution**

**Symptoms:**

- One deployment handles all traffic
- Other deployments idle

**Solutions:**

1. Use correct routing strategy:
   ```yaml
   router_settings:
     routing_strategy: "usage-based-routing-v2"  # Not "simple-shuffle"
   ```

2. Set accurate TPM/RPM:
   ```yaml
   model_info:
     tpm: 1200000  # Match Azure quota exactly
     rpm: 500      # Match Azure quota exactly
   ```

3. Enable pre-call checks:

   ```yaml
   router_settings:
     enable_pre_call_checks: true
   ```

**Issue 4: Circular Fallback Loop**

**Symptoms:**
```
Error: Maximum fallback depth exceeded
```

**Bad Configuration:**

```yaml
fallbacks:
  - {gpt-5-mini: [gpt-5-nano]}
  - {gpt-5-nano: [gpt-5-mini]}  # Circular!
```

**Good Configuration:**

```yaml
fallbacks:
  - {gpt-5-mini: [gpt-4o]}     # Linear chain
  - {gpt-5-nano: [gpt-5-mini, gpt-4o]}  # Multi-level
```

**Issue 5: Default Fallback Bottleneck**

**Symptoms:**

```
Error: Rate limit on default fallback model
Multiple models failing simultaneously
High latency during peak traffic
```

**Root Cause:**

Default fallback has insufficient capacity for overflow traffic.

**Solutions:**

**1. Use load-balanced default fallback:**

   ```yaml
   # Add multiple deployments of default fallback
   - model_name: gpt-4o
     litellm_params: {model: azure/gpt-4o-2, ...}
     model_info: {tpm: 1200000, rpm: 500}
   - model_name: gpt-4o
     litellm_params: {model: azure/gpt-4o-3, ...}
     model_info: {tpm: 916000, rpm: 500}
   - model_name: gpt-4o
     litellm_params: {model: azure/gpt-4o-4, ...}
     model_info: {tpm: 977000, rpm: 500}
   
   litellm_settings:

     default_fallbacks: [gpt-4o]  # Now has 3M+ total TPM
   ```

**2. Increase quota on default fallback model:**

   - Contact Azure support to increase TPM/RPM limits
   - Switch to a higher-tier deployment

**3. Add secondary default fallback:**

   ```yaml
   litellm_settings:
     default_fallbacks: [gpt-4o, gpt-5-mini]  # Chain of fallbacks
   ```

---

## Performance Metrics

**Expected Improvements**

| Configuration | Availability | Throughput | Cost | Latency |
|---------------|-------------|------------|------|---------|
| `Single Model` | 99.0% | 1x | Low | Baseline |
| `3x Load Balanced` | 99.9% | 3x | Medium | +5-10ms |
| `Load Balanced + Fallback` | 99.99% | 3x | Medium | +10-15ms |
| `Multi-tier Fallbacks` | 99.999% | 3-4x | High | +15-25ms |

??? Example "Real-World Example"

    **Setup:** 3x gpt-4o deployments + gpt-5-mini fallback

    **Results:**

    - Throughput: `300%` increase (3x deployments)
    - ⏱Latency: `+12ms` average (routing overhead)
    - Cost: `15%` savings (cheaper fallback handles 10% of traffic)
    - Availability: `99.95%` uptime (vs 99.0% single deployment)

---

## Testing Your Configuration

**Test Load Balancing**

```python
import asyncio
from litellm import acompletion

async def test_load_balancing():
    """Send 10 requests and see which deployments are used"""
    for i in range(10):
        response = await acompletion(
            model="gpt-4o",
            messages=[{"role": "user", "content": f"Test {i}"}],
            api_base="http://localhost:4000"
        )
        print(f"Request {i}: Used model: {response.model}")

asyncio.run(test_load_balancing())
```

**Expected Output:**

```
Request 0: Used model: azure/gpt-4o-2
Request 1: Used model: azure/gpt-4o-3
Request 2: Used model: azure/gpt-4o-4
Request 3: Used model: azure/gpt-4o-2  # Balanced distribution
...
```

**Test Fallback**

```python
async def test_fallback():
    """Request a model that will fail and fallback"""
    try:
        response = await acompletion(
            model="gpt-5-chat",
            messages=[{"role": "user", "content": "Test"}],
            api_base="http://localhost:4000",
            max_tokens=999999  # Force context limit error
        )
        print(f"Used fallback model: {response.model}")
    except Exception as e:
        print(f"Fallback failed: {e}")

asyncio.run(test_fallback())
```

**Test Default Fallback Capacity**

```python
async def stress_test_default_fallback():
    """Stress test default fallback with concurrent requests"""
    import time
    
    async def make_request(i):
        start = time.time()
        try:
            response = await acompletion(
                model="undefined-model",  # Will use default fallback
                messages=[{"role": "user", "content": f"Test {i}"}],
                api_base="http://localhost:4000"
            )
            elapsed = time.time() - start
            print(f"Request {i}: Success in {elapsed:.2f}s - Model: {response.model}")
        except Exception as e:
            elapsed = time.time() - start
            print(f"Request {i}: Failed in {elapsed:.2f}s - Error: {str(e)[:50]}")
    
    # Send 50 concurrent requests to test fallback capacity
    tasks = [make_request(i) for i in range(50)]
    await asyncio.gather(*tasks)

asyncio.run(stress_test_default_fallback())
```

---

## Summary

**Quick Reference**

| Feature | Configuration Location | Key Parameter |
|---------|----------------------|---------------|
| **Load Balancing** | `model_list` | Same `model_name`, different deployments |
| **Routing Strategy** | `router_settings` | `routing_strategy: "usage-based-routing-v2"` |
| **Model Fallbacks** | `litellm_settings.fallbacks` | `{primary: [fallback1, fallback2]}` |
| **Context Fallbacks** | `litellm_settings.context_window_fallbacks` | `{small_context: [large_context]}` |
| **Default Fallback** | `litellm_settings.default_fallbacks` | `[gpt-4o]` **Must have high TPM/RPM** |
| **Retry Policy** | `router_settings.retry_policy` | `RateLimitErrorRetries: 3` |
| **Cooldown** | `router_settings` | `cooldown_time: 60` |

**Recommended Production Config**

```yaml
model_list:
  # Default fallback: Load-balanced gpt-4o with HIGH capacity
  - model_name: gpt-4o
    litellm_params: {model: azure/gpt-4o-2, ...}
    model_info: {tpm: 1200000, rpm: 500}  # High limit
  - model_name: gpt-4o
    litellm_params: {model: azure/gpt-4o-3, ...}
    model_info: {tpm: 916000, rpm: 500}
  - model_name: gpt-4o
    litellm_params: {model: azure/gpt-4o-4, ...}
    model_info: {tpm: 977000, rpm: 500}

litellm_settings:
  fallbacks:
    - {gpt-4o: [gpt-5-mini]}
  default_fallbacks: [gpt-4o]  # High-capacity load-balanced model

router_settings:
  routing_strategy: "usage-based-routing-v2"
  num_retries: 3
  enable_pre_call_checks: true
  cooldown_time: 60
  retry_policy:
    RateLimitErrorRetries: 3
    TimeoutErrorRetries: 3
```

**Critical Reminders**

**DEFAULT FALLBACK MUST HAVE HIGH RATE LIMITS**

- It handles overflow from ALL models
- Should be load-balanced with multiple deployments
- Typical requirement: 2-5x the TPM of any single primary model
- Monitor closely during production to ensure adequate capacity

---

## Additional Resources

- **LiteLLM Docs:** https://docs.litellm.ai/docs/routing
- **Azure OpenAI Rate Limits:** https://learn.microsoft.com/en-us/azure/ai-services/openai/quotas-limits
- **Load Balancing Strategies:** https://docs.litellm.ai/docs/routing#advanced-routing-strategies

---