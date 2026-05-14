#!/usr/bin/env python3
"""
Bitcoin Price Paths Generation

This script:
1. Allows manual fitting of a normal-based distribution to historical Bitcoin price data
   with adjustable parameters for skew, kurtosis, and other relevant factors
2. Generates Monte Carlo simulations of Bitcoin price paths over 100 years
3. Exports the price paths to a .npz file for use in the STRC valuation model
4. Generates and saves visualization charts

You can manually adjust the distribution parameters to match empirical data characteristics.
"""

# ============================================================================
# CONFIGURATION - MANUAL DISTRIBUTION PARAMETERS
# ============================================================================

HISTORICAL_DATA_PERIOD = 'max'        # Historical data period ('max' = all available, '10y', etc.)

# Manual Distribution Parameters (adjust these to fit your data)
# Base Normal Distribution Parameters
DIST_MEAN = -0.008              # Mean (location parameter)
DIST_STD = 0.16                   # Standard deviation (scale parameter)

# Skewness Parameter
DIST_SKEW = -0.25                   # Skewness (0 = symmetric, >0 = right-skewed, <0 = left-skewed)
                                  # Range: typically -2 to +2 for reasonable distributions

# Kurtosis Parameter (excess kurtosis)
DIST_KURTOSIS = 5                 # Excess kurtosis (0 = normal, >0 = fat tails, <0 = thin tails)
                                  # Range: typically -1 to +5 for reasonable distributions

# Additional Parameters (for advanced control)
DIST_TAIL_WEIGHT = 1.0            # Tail weight multiplier (1.0 = normal, >1.0 = heavier tails)
DIST_ASYMMETRY = 0.0              # Additional asymmetry parameter (0 = symmetric)

# Simulation Parameters
NUM_SIMULATIONS = 10000          # Number of Monte Carlo simulation runs
SIMULATION_YEARS = 100            # Projection period in years
MEAN_CAGR = 0.0                   # Mean Compound Annual Growth Rate (Bitcoin trends to zero)

# Output Configuration
OUTPUT_DIR = "plots"              # Directory for saving charts
OUTPUT_FILE_NPZ = "btc_price_paths_scenarios.npz"  # Output file for price paths

# ============================================================================
# IMPORT LIBRARIES
# ============================================================================

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for saving plots
import matplotlib.pyplot as plt
from scipy import stats
from scipy.stats import skewnorm, norm
from scipy.optimize import minimize
from scipy.special import gamma as gamma_func
import yfinance as yf
import warnings
import os
import time
import sys
import traceback
import json
warnings.filterwarnings('ignore')

# Optional: Check for multiprocessing support
try:
    from multiprocessing import Pool, cpu_count
    from concurrent.futures import ProcessPoolExecutor, as_completed
    MULTIPROCESSING_AVAILABLE = True
    NUM_CPUS = cpu_count()
except ImportError:
    MULTIPROCESSING_AVAILABLE = False
    NUM_CPUS = 1

# Optional: Check for Numba support
try:
    import numba
    from numba import jit, prange
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    print("Warning: Numba not available. Install with: pip install numba (for faster simulation)")

# ============================================================================
# DISTRIBUTION FUNCTIONS
# ============================================================================

def manual_distribution_pdf(x, mean, std, skew, kurtosis, tail_weight=1.0, asymmetry=0.0):
    """
    Generate PDF values for a normal-based distribution with manual parameters.
    
    Parameters:
    -----------
    x : array-like
        Values at which to evaluate the PDF
    mean : float
        Mean (location parameter)
    std : float
        Standard deviation (scale parameter)
    skew : float
        Skewness parameter (0 = symmetric, >0 = right-skewed, <0 = left-skewed)
    kurtosis : float
        Excess kurtosis (0 = normal, >0 = fat tails, <0 = thin tails)
    tail_weight : float, optional
        Tail weight multiplier (default: 1.0)
    asymmetry : float, optional
        Additional asymmetry parameter (default: 0.0)
    
    Returns:
    --------
    pdf_values : array
        PDF values at x
    """
    x = np.asarray(x)
    
    # Start with a normal distribution
    base_pdf = norm.pdf(x, loc=mean, scale=std)
    
    # Apply skewness using skew-normal distribution
    if abs(skew) > 1e-6:
        # Convert skewness to skew-normal parameter
        a_skew = skew * np.sqrt(np.pi / 2)
        
        # Adjust scale to maintain variance
        scale_adjusted = std / np.sqrt(1 - 2 * a_skew**2 / np.pi) if abs(a_skew) < np.sqrt(np.pi/2) else std
        
        # Generate skew-normal PDF
        skewed_pdf = skewnorm.pdf(x, a=a_skew, loc=mean, scale=scale_adjusted)
        
        # Blend with base normal based on skew magnitude
        skew_weight = min(abs(skew) / 2.0, 1.0)
        pdf = (1 - skew_weight) * base_pdf + skew_weight * skewed_pdf
    else:
        pdf = base_pdf
    
    # Apply kurtosis by adjusting tail weights
    if abs(kurtosis) > 1e-6:
        center = mean
        distance_from_center = np.abs(x - center)
        tail_factor = distance_from_center / std
        
        if kurtosis > 0:
            tail_multiplier = 1 + kurtosis * tail_factor**2 * tail_weight / 10.0
        else:
            tail_multiplier = 1 + kurtosis * tail_factor**2 * tail_weight / 10.0
            tail_multiplier = np.maximum(tail_multiplier, 0.1)
        
        pdf = pdf * tail_multiplier
    
    # Apply additional asymmetry if specified
    if abs(asymmetry) > 1e-6:
        shift_factor = asymmetry * (x - mean) / std
        pdf = pdf * (1 + shift_factor)
        pdf = np.maximum(pdf, 0)
    
    # Normalize to ensure it's a proper PDF
    if len(x) > 1:
        dx = np.diff(x)
        if len(dx) > 0:
            integral = np.trapz(pdf, x)
            if integral > 0:
                pdf = pdf / integral
    
    return pdf


def precompute_cdf(mean, std, skew, kurtosis, tail_weight=1.0, asymmetry=0.0, x_range=None, n_points=10000):
    """
    Pre-compute the CDF for the manual distribution. This is much faster than recomputing
    it for each sample.
    
    Returns:
    --------
    x_fine : array
        X values for the CDF
    cdf : array
        Cumulative distribution function values
    """
    if x_range is None:
        x_min = mean - 5 * std
        x_max = mean + 5 * std
    else:
        x_min, x_max = x_range
    
    # Create fine grid for CDF calculation
    x_fine = np.linspace(x_min, x_max, n_points)
    pdf_fine = manual_distribution_pdf(x_fine, mean, std, skew, kurtosis, tail_weight, asymmetry)
    
    # Normalize PDF
    dx_fine = x_fine[1] - x_fine[0]
    pdf_fine = pdf_fine / (np.sum(pdf_fine) * dx_fine)
    
    # Calculate CDF
    cdf = np.cumsum(pdf_fine[:-1] * dx_fine)
    cdf = np.concatenate([[0], cdf])
    cdf = cdf / cdf[-1] if cdf[-1] > 0 else cdf
    
    return x_fine, cdf


# Numba-accelerated version of sample_from_precomputed_cdf
if NUMBA_AVAILABLE:
    @jit(nopython=True, cache=True)
    def sample_from_precomputed_cdf_numba(x_fine, cdf, u):
        """Numba-accelerated CDF sampling using binary search."""
        n_samples = len(u)
        samples = np.empty(n_samples)
        n_cdf = len(cdf)
        
        for i in prange(n_samples):
            u_val = u[i]
            
            if u_val <= cdf[0]:
                samples[i] = x_fine[0]
                continue
            if u_val >= cdf[n_cdf - 1]:
                samples[i] = x_fine[n_cdf - 1]
                continue
            
            # Binary search
            left = 0
            right = n_cdf - 1
            
            while right - left > 1:
                mid = (left + right) // 2
                if cdf[mid] < u_val:
                    left = mid
                else:
                    right = mid
            
            # Linear interpolation
            cdf_left = cdf[left]
            cdf_right = cdf[right]
            if abs(cdf_right - cdf_left) < 1e-10:
                samples[i] = x_fine[left]
            else:
                t = (u_val - cdf_left) / (cdf_right - cdf_left)
                samples[i] = x_fine[left] * (1 - t) + x_fine[right] * t
        
        return samples


def sample_from_precomputed_cdf(x_fine, cdf, n_samples):
    """
    Sample from a pre-computed CDF. This is much faster than recomputing the CDF.
    Uses Numba acceleration if available.
    """
    u = np.random.uniform(0, 1, n_samples)
    if NUMBA_AVAILABLE:
        return sample_from_precomputed_cdf_numba(np.asarray(x_fine), np.asarray(cdf), u)
    else:
        return np.interp(u, cdf, x_fine)


# ============================================================================
# MULTIPROCESSING WORKER FUNCTION (must be top-level for pickling)
# ============================================================================

def generate_chunk_worker(chunk_data):
    """
    Generate a chunk of price path simulations. Designed for parallel execution.
    This function runs in worker processes, so it must be self-contained.
    
    Parameters:
    -----------
    chunk_data : tuple
        (chunk_idx, chunk_size, starting_price, x_fine, cdf, total_months, base_seed, num_simulations)
    
    Returns:
    --------
    tuple : (chunk_idx, price_paths_array)
    """
    import numpy as np
    
    try:
        chunk_idx, chunk_size, starting_price, x_fine, cdf, total_months, base_seed, num_simulations = chunk_data
        
        # Convert to numpy arrays
        x_fine = np.asarray(x_fine, dtype=np.float64)
        cdf = np.asarray(cdf, dtype=np.float64)
        starting_price = float(starting_price)
        total_months = int(total_months)
        base_seed = int(base_seed)
        num_simulations = int(num_simulations)
        chunk_size = int(chunk_size)
        chunk_idx = int(chunk_idx)
        
        # Validate CDF is monotonically increasing
        if len(cdf) > 1 and not np.all(np.diff(cdf) >= -1e-10):
            sort_idx = np.argsort(cdf)
            cdf = cdf[sort_idx]
            x_fine = x_fine[sort_idx]
        
        # Ensure CDF starts at 0 and ends at 1
        cdf[0] = 0.0
        cdf[-1] = 1.0
        
        # Calculate actual chunk size
        start_sim = chunk_idx * chunk_size
        end_sim = min(start_sim + chunk_size, num_simulations)
        actual_chunk_size = end_sim - start_sim
        
        if actual_chunk_size <= 0:
            raise ValueError(f"Invalid chunk size: {actual_chunk_size} for chunk {chunk_idx}")
        
        # Set random seed for this chunk
        np.random.seed(base_seed + chunk_idx)
        
        # Sample monthly log returns for this chunk
        n_samples = actual_chunk_size * (total_months - 1)
        u = np.random.uniform(0, 1, n_samples)
        u = np.clip(u, 0.0, 1.0)
        
        # Use np.interp for CDF sampling
        chunk_log_returns = np.interp(u, cdf, x_fine)
        
        # Reshape to (actual_chunk_size, TOTAL_MONTHS - 1)
        chunk_log_returns = chunk_log_returns.reshape(actual_chunk_size, total_months - 1)
        
        # Generate price paths for this chunk (vectorized)
        chunk_price_paths = np.zeros((actual_chunk_size, total_months), dtype=np.float32)
        chunk_price_paths[:, 0] = starting_price
        log_prices = np.log(starting_price) + np.cumsum(chunk_log_returns, axis=1)
        chunk_price_paths[:, 1:] = np.maximum(np.exp(log_prices), 0.01).astype(np.float32)
        
        return (chunk_idx, chunk_price_paths)
    
    except Exception as e:
        error_msg = f"Error in chunk {chunk_idx if 'chunk_idx' in locals() else 'unknown'}: {str(e)}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr, flush=True)
        raise


# ============================================================================
# CHART GENERATION FUNCTIONS
# ============================================================================

def create_side_by_side_comparison(btc_returns, bin_min, bin_max, n_bins_count, dist_params, output_dir):
    """Create a side-by-side comparison plot with specified number of bins."""
    bins = np.linspace(bin_min, bin_max, n_bins_count + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    bin_width = bins[1] - bins[0]
    
    # Calculate empirical histogram
    empirical_density, _ = np.histogram(btc_returns.values, bins=bins, density=True)
    
    # Calculate manual distribution PDF
    manual_density = manual_distribution_pdf(
        bin_centers, 
        mean=dist_params['mean'],
        std=dist_params['std'],
        skew=dist_params['skew'],
        kurtosis=dist_params['kurtosis'],
        tail_weight=dist_params['tail_weight'],
        asymmetry=dist_params['asymmetry']
    )
    
    # Normalize manual density
    manual_integral = np.sum(manual_density) * bin_width
    if manual_integral > 0:
        manual_density_normalized = manual_density / manual_integral
    else:
        manual_density_normalized = manual_density
    
    # Create plot
    fig, ax = plt.subplots(1, 1, figsize=(12, 6))
    width = bin_width * 0.35
    
    ax.bar(bin_centers - width/2, empirical_density, width, 
            label='Empirical', alpha=0.7, color='blue', edgecolor='black')
    ax.bar(bin_centers + width/2, manual_density_normalized, width,
            label='Manual Distribution', alpha=0.7, color='red', edgecolor='black')
    
    ax.set_xlabel('Monthly Log Return', fontsize=12)
    ax.set_ylabel('Probability Density', fontsize=12)
    ax.set_title(f'Side-by-Side Comparison ({n_bins_count} bins)', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, f'distribution_comparison_{n_bins_count}bins.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved: {output_path}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function."""
    
    # Create output directory for plots
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Output directory: {OUTPUT_DIR}/")
    
    # Print configuration
    print("\n" + "=" * 70)
    print("MANUAL DISTRIBUTION FITTING CONFIGURATION")
    print("=" * 70)
    print(f"Historical Data Period: {HISTORICAL_DATA_PERIOD}")
    print(f"Model: Normal Distribution with Manual Parameters")
    print(f"\nDistribution Parameters:")
    print(f"  Mean: {DIST_MEAN:.4f}")
    print(f"  Std Dev: {DIST_STD:.4f}")
    print(f"  Skewness: {DIST_SKEW:.4f}")
    print(f"  Excess Kurtosis: {DIST_KURTOSIS:.4f}")
    print(f"  Tail Weight: {DIST_TAIL_WEIGHT:.4f}")
    print(f"  Asymmetry: {DIST_ASYMMETRY:.4f}")
    print("=" * 70)
    
    print("\nLibraries imported successfully!")
    if MULTIPROCESSING_AVAILABLE:
        print(f"  Multiprocessing available: {NUM_CPUS} CPU cores")
    else:
        print("  Multiprocessing not available (using single-threaded mode)")
    if NUMBA_AVAILABLE:
        print(f"  Numba JIT compilation: Available (v{numba.__version__})")
    else:
        print("  Numba JIT compilation: Not available (slower execution)")
    
    # ========================================================================
    # Step 1: Load Historical Bitcoin Data from JSON
    # ========================================================================
    print(f"\n{'='*70}")
    print("STEP 1: LOADING HISTORICAL BITCOIN DATA FROM JSON")
    print(f"{'='*70}")
    print("Loading historical Bitcoin data from btc_historical_data.json...")

    # Load BTC historical data from JSON
    json_file = 'btc_historical_data.json'
    try:
        with open(json_file, 'r') as f:
            btc_json_data = json.load(f)

        # Convert dates back to pandas datetime
        daily_dates = pd.to_datetime(btc_json_data['daily_prices']['dates'])
        monthly_dates = pd.to_datetime(btc_json_data['monthly_returns']['dates'])

        # Create pandas Series for prices and returns
        btc_prices = pd.Series(
            btc_json_data['daily_prices']['prices'],
            index=daily_dates,
            name='Close'
        )
        btc_returns = pd.Series(
            btc_json_data['monthly_returns']['returns'],
            index=monthly_dates,
            name='monthly_returns'
        )

        print(f"\nData loaded successfully!")
        print(f"Date range: {btc_prices.index[0].date()} to {btc_prices.index[-1].date()}")
        print(f"Daily observations: {len(btc_prices):,}")
        print(f"Monthly observations: {len(btc_returns):,}")
        print(f"Current Bitcoin price: ${btc_prices.iloc[-1]:,.2f}")
        print(f"\nMonthly return statistics:")
        print(f"  Mean (annualized): {btc_returns.mean() * 12:.2%}")
        print(f"  Std Dev (annualized): {btc_returns.std() * np.sqrt(12):.2%}")
        print(f"  Skewness: {btc_returns.skew():.3f}")
        print(f"  Kurtosis: {btc_returns.kurtosis():.3f}")

    except FileNotFoundError:
        print(f"  ✗ Error: {json_file} not found!")
        print(f"  Please run fetch_data.py first to generate the historical data.")
        return
    except Exception as e:
        print(f"  ✗ Error loading {json_file}: {e}")
        return
    
    # ========================================================================
    # Step 2: Generate Bitcoin Price Paths
    # ========================================================================
    print(f"\n{'='*70}")
    print("STEP 2: GENERATE BITCOIN PRICE PATHS")
    print(f"{'='*70}")
    
    # Fetch current Bitcoin price
    try:
        btc_ticker = yf.Ticker("BTC-USD")
        btc_data = btc_ticker.history(period="1d")
        if len(btc_data) > 0:
            CURRENT_BITCOIN_PRICE = float(btc_data['Close'].iloc[-1])
            btc_price_source = "Yahoo Finance"
        else:
            CURRENT_BITCOIN_PRICE = 92395.03
            btc_price_source = "Default (Yahoo Finance returned no data)"
    except Exception as e:
        CURRENT_BITCOIN_PRICE = 92395.03
        btc_price_source = f"Default (Yahoo Finance error)"
    
    MONTHS_PER_YEAR = 12
    TOTAL_MONTHS = SIMULATION_YEARS * MONTHS_PER_YEAR
    
    print("=" * 70)
    print("PRICE PATH GENERATION CONFIGURATION")
    print("=" * 70)
    print(f"Number of Simulations: {NUM_SIMULATIONS:,}")
    print(f"Simulation Period: {SIMULATION_YEARS} years ({TOTAL_MONTHS:,} months)")
    print(f"Mean CAGR constraint: {MEAN_CAGR:.1%} (Bitcoin trends to zero)")
    print(f"Current Bitcoin Price: ${CURRENT_BITCOIN_PRICE:,.2f} ({btc_price_source})")
    print(f"\nDistribution Parameters:")
    print(f"  Mean: {DIST_MEAN:.4f}")
    print(f"  Std Dev: {DIST_STD:.4f}")
    print(f"  Skewness: {DIST_SKEW:.4f}")
    print(f"  Excess Kurtosis: {DIST_KURTOSIS:.4f}")
    print(f"  Tail Weight: {DIST_TAIL_WEIGHT:.4f}")
    print(f"  Asymmetry: {DIST_ASYMMETRY:.4f}")
    print("=" * 70)
    
    # Generate scenarios: custom percentages
    scenario_pcts = np.array([-0.75, -0.50, -0.40, -0.30, -0.25, -0.20, -0.15, -0.10, -0.05, -0.01, 0.00,
                              0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75])
    NUM_SCENARIOS = len(scenario_pcts)
    
    print(f"\n{'='*70}")
    print(f"SCALING-BASED SCENARIO GENERATION")
    print(f"{'='*70}")
    print(f"Generating 1 baseline scenario with {NUM_SIMULATIONS:,} simulations")
    print(f"Then scaling to create {NUM_SCENARIOS} scenarios (custom percentages)")
    print(f"Simulation period: {SIMULATION_YEARS} years ({TOTAL_MONTHS:,} months)")
    print(f"Mean CAGR constraint: {MEAN_CAGR:.1%} (Bitcoin trends to zero)")
    print(f"\nUsing Manual Distribution parameters:")
    print(f"  Mean: {DIST_MEAN:.4f}")
    print(f"  Std Dev: {DIST_STD:.4f}")
    print(f"  Skewness: {DIST_SKEW:.4f}")
    print(f"  Excess Kurtosis: {DIST_KURTOSIS:.4f}")
    
    print(f"\nNote: DIST_MEAN = {DIST_MEAN:.4f} ensures zero drift (CAGR = 0)")
    print(f"Note: Using scaling optimization - mathematically equivalent, ~21x faster!")
    
    # Pre-compute CDF
    print("\nPre-computing CDF for optimized sampling...")
    np.random.seed(42)
    
    return_range_factor = 1 + abs(DIST_KURTOSIS) / 2.0
    x_range = (DIST_MEAN - 5 * DIST_STD * return_range_factor, 
               DIST_MEAN + 5 * DIST_STD * return_range_factor)
    
    x_fine, cdf = precompute_cdf(
        DIST_MEAN, DIST_STD, DIST_SKEW, DIST_KURTOSIS,
        DIST_TAIL_WEIGHT, DIST_ASYMMETRY, x_range
    )
    print(f"  ✓ CDF pre-computed ({len(x_fine):,} points)")
    
    # Convert to numpy arrays
    x_fine = np.asarray(x_fine, dtype=np.float64)
    cdf = np.asarray(cdf, dtype=np.float64)
    
    # Validate and fix CDF if needed
    if len(cdf) > 1:
        if not np.all(np.diff(cdf) >= -1e-10):
            print("  Warning: CDF is not strictly increasing, sorting...")
            sort_idx = np.argsort(cdf)
            cdf = cdf[sort_idx]
            x_fine = x_fine[sort_idx]
        cdf[0] = 0.0
        cdf[-1] = 1.0
    
    # Generate baseline scenario with multiprocessing
    print(f"\n{'='*70}")
    print(f"GENERATING BASELINE SCENARIO (0%) - PARALLEL PROCESSING")
    print(f"{'='*70}")
    baseline_starting_price = CURRENT_BITCOIN_PRICE
    print(f"Starting price: ${baseline_starting_price:,.2f}")
    
    start_time = time.time()
    
    # Configuration for parallel processing
    CHUNK_SIZE = max(10000, NUM_SIMULATIONS // NUM_CPUS) if MULTIPROCESSING_AVAILABLE else NUM_SIMULATIONS
    NUM_CHUNKS = (NUM_SIMULATIONS + CHUNK_SIZE - 1) // CHUNK_SIZE
    
    print(f"Parallel processing configuration:")
    print(f"  Total simulations: {NUM_SIMULATIONS:,}")
    print(f"  Chunk size: {CHUNK_SIZE:,} simulations per chunk")
    print(f"  Number of chunks: {NUM_CHUNKS}")
    if MULTIPROCESSING_AVAILABLE:
        max_workers = min(NUM_CPUS, NUM_CHUNKS)
        print(f"  Worker processes: {max_workers}")
    
    # Prepare chunk data
    chunk_data_list = []
    for chunk_idx in range(NUM_CHUNKS):
        chunk_data_list.append((
            chunk_idx, CHUNK_SIZE, float(baseline_starting_price),
            x_fine.tolist(), cdf.tolist(),
            int(TOTAL_MONTHS), 42, int(NUM_SIMULATIONS)
        ))
    
    # Generate chunks in parallel
    if MULTIPROCESSING_AVAILABLE and NUM_CHUNKS > 1:
        print(f"\nGenerating {NUM_CHUNKS} chunks in parallel using {max_workers} workers...")
        chunk_results = []
        
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk = {executor.submit(generate_chunk_worker, data): i 
                              for i, data in enumerate(chunk_data_list)}
            
            completed = 0
            for future in as_completed(future_to_chunk):
                chunk_idx = future_to_chunk[future]
                try:
                    result = future.result(timeout=300)
                    chunk_results.append(result)
                    completed += 1
                    if completed % max(1, NUM_CHUNKS // 10) == 0 or completed == NUM_CHUNKS:
                        print(f"  Progress: {completed}/{NUM_CHUNKS} chunks completed ({completed*100/NUM_CHUNKS:.0f}%)")
                except Exception as exc:
                    print(f"  ✗ Chunk {chunk_idx} generated an exception: {exc}")
                    raise
        
        chunk_results.sort(key=lambda x: x[0])
        print(f"  Combining {len(chunk_results)} chunks...")
        baseline_price_paths = np.concatenate([chunk[1] for chunk in chunk_results], axis=0).astype(np.float32)
    else:
        # Sequential fallback
        print(f"\nGenerating {NUM_CHUNKS} chunks sequentially...")
        chunk_results = []
        for chunk_idx, chunk_data in enumerate(chunk_data_list):
            result = generate_chunk_worker(chunk_data)
            chunk_results.append(result)
            if (chunk_idx + 1) % max(1, NUM_CHUNKS // 10) == 0 or (chunk_idx + 1) == NUM_CHUNKS:
                print(f"  Progress: {chunk_idx + 1}/{NUM_CHUNKS} chunks completed ({100*(chunk_idx+1)/NUM_CHUNKS:.0f}%)")
        
        chunk_results.sort(key=lambda x: x[0])
        baseline_price_paths = np.concatenate([chunk[1] for chunk in chunk_results], axis=0).astype(np.float32)
    
    baseline_time = time.time() - start_time
    print(f"  ✓ Baseline scenario completed in {baseline_time:.2f} seconds")
    print(f"  Generated {baseline_price_paths.shape[0]:,} simulations × {baseline_price_paths.shape[1]:,} months")
    
    # Scale baseline to create all scenarios
    print(f"\n{'='*70}")
    print(f"SCALING BASELINE TO CREATE {NUM_SCENARIOS} SCENARIOS")
    print(f"{'='*70}")
    scaling_start = time.time()
    
    all_scenarios_data = np.zeros((NUM_SCENARIOS, NUM_SIMULATIONS, TOTAL_MONTHS), dtype=np.float32)
    all_starting_prices = np.zeros(NUM_SCENARIOS, dtype=np.float32)
    all_starting_pcts = np.zeros(NUM_SCENARIOS, dtype=np.float32)
    
    for i, price_pct_change in enumerate(scenario_pcts):
        scale_factor = 1 + price_pct_change
        all_starting_pcts[i] = price_pct_change
        all_starting_prices[i] = baseline_starting_price * scale_factor
        all_scenarios_data[i] = baseline_price_paths * scale_factor
    
    all_scenarios = []
    for i, price_pct_change in enumerate(scenario_pcts):
        all_scenarios.append({
            'starting_price_pct': float(all_starting_pcts[i]),
            'starting_price': float(all_starting_prices[i]),
            'price_paths': all_scenarios_data[i]
        })
    
    scaling_time = time.time() - scaling_start
    total_time = time.time() - start_time
    
    print(f"  ✓ Created all {NUM_SCENARIOS} scenarios in {scaling_time:.2f} seconds")
    print(f"  Scaling speed: {NUM_SCENARIOS * NUM_SIMULATIONS * TOTAL_MONTHS / scaling_time / 1e6:.1f}M elements/second")
    print(f"\n{'='*70}")
    print(f"✓ COMPLETED ALL SCENARIOS!")
    print(f"{'='*70}")
    print(f"  Baseline generation: {baseline_time:.2f} seconds")
    print(f"  Scaling operation: {scaling_time:.2f} seconds")
    print(f"  Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
    print(f"  Total simulations: {NUM_SCENARIOS * NUM_SIMULATIONS:,}")
    print(f"  Total data points: {NUM_SCENARIOS * NUM_SIMULATIONS * TOTAL_MONTHS:,}")
    print(f"  Speedup vs generating separately: ~{NUM_SCENARIOS}x faster")
    
    # Plot baseline scenario paths
    baseline_scenario = all_scenarios[NUM_SCENARIOS // 2]
    baseline_prices = np.array(baseline_scenario['price_paths'])
    
    print(f"\n{'='*70}")
    print("BASELINE SCENARIO (0% change) STATISTICS")
    print(f"{'='*70}")
    print(f"Price statistics across all simulations:")
    print(f"  Initial price: ${baseline_scenario['starting_price']:,.2f}")
    print(f"  Final price (mean): ${baseline_prices[:, -1].mean():,.2f}")
    print(f"  Final price (median): ${np.median(baseline_prices[:, -1]):,.2f}")
    print(f"  Final price (std): ${baseline_prices[:, -1].std():,.2f}")
    print(f"  Final price (min): ${baseline_prices[:, -1].min():,.2f}")
    print(f"  Final price (max): ${baseline_prices[:, -1].max():,.2f}")
    
    # Plot sample paths
    plt.figure(figsize=(14, 6))
    sample_paths = min(100, NUM_SIMULATIONS)
    for i in range(sample_paths):
        plt.plot(baseline_prices[i, :], alpha=0.1, linewidth=0.5, color='lightblue')
    
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    percentile_colors = {5: 'black', 10: 'purple', 25: 'blue', 50: 'green', 75: 'orange', 90: 'red', 95: 'darkred'}
    percentile_styles = {5: '--', 10: '--', 25: '--', 50: '-', 75: '--', 90: '--', 95: '--'}
    
    for p in percentiles:
        percentile_path = np.percentile(baseline_prices, p, axis=0)
        plt.plot(percentile_path, color=percentile_colors[p], linestyle=percentile_styles[p],
                linewidth=2, label=f'{p}th percentile', alpha=0.8)
    
    plt.plot(baseline_prices.mean(axis=0), 'r-', linewidth=2, label='Mean path', alpha=0.7)
    plt.axhline(y=baseline_scenario['starting_price'], color='g', linestyle=':', linewidth=1.5, label='Initial price', alpha=0.7)
    plt.title(f'Baseline Scenario (0%): Sample of {sample_paths} Simulated Bitcoin Price Paths ({SIMULATION_YEARS} years)')
    plt.xlabel('Month')
    plt.ylabel('Bitcoin Price (USD)')
    plt.legend(loc='best', fontsize=9)
    plt.grid(True, alpha=0.3)
    plt.yscale('log')
    
    output_path = os.path.join(OUTPUT_DIR, 'baseline_scenario_paths.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved: {output_path}")

    # Create 10-year linear scale version (120 months, 0-1M range)
    print(f"\n  Creating 10-year linear scale plot...")
    plt.figure(figsize=(14, 6))
    sample_paths = min(100, NUM_SIMULATIONS)

    # Only show first 120 months (10 years)
    months_to_show = 120
    baseline_prices_10y = baseline_prices[:, :months_to_show]

    for i in range(sample_paths):
        plt.plot(baseline_prices_10y[i, :], alpha=0.1, linewidth=0.5, color='lightblue')

    percentiles = [5, 10, 25, 50, 75, 90, 95]
    percentile_colors = {5: 'black', 10: 'purple', 25: 'blue', 50: 'green', 75: 'orange', 90: 'red', 95: 'darkred'}
    percentile_styles = {5: '--', 10: '--', 25: '--', 50: '-', 75: '--', 90: '--', 95: '--'}

    for p in percentiles:
        percentile_path = np.percentile(baseline_prices_10y, p, axis=0)
        plt.plot(percentile_path, color=percentile_colors[p], linestyle=percentile_styles[p],
                linewidth=2, label=f'{p}th percentile', alpha=0.8)

    plt.plot(baseline_prices_10y.mean(axis=0), 'r-', linewidth=2, label='Mean path', alpha=0.7)
    plt.axhline(y=baseline_scenario['starting_price'], color='g', linestyle=':', linewidth=1.5, label='Initial price', alpha=0.7)
    plt.title(f'Baseline Scenario (0%): Sample of {sample_paths} Simulated Bitcoin Price Paths (10 years)')
    plt.xlabel('Month')
    plt.ylabel('Bitcoin Price (USD)')
    plt.legend(loc='best', fontsize=9)
    plt.grid(True, alpha=0.3)
    plt.ylim(0, 1000000)  # Linear scale from 0 to 1 million

    output_path_10y = os.path.join(OUTPUT_DIR, 'baseline_scenario_paths_10years_linear.png')
    plt.savefig(output_path_10y, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved: {output_path_10y}")

    # ========================================================================
    # Step 3: Export Price Paths (Parallelized)
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"STEP 3: EXPORTING PRICE PATHS (PARALLELIZED)")
    print(f"{'='*70}")
    print(f"Exporting {NUM_SCENARIOS} scenarios...")
    print(f"  Each scenario: {NUM_SIMULATIONS:,} simulations × {TOTAL_MONTHS:,} months")
    
    export_start = time.time()
    
    # Prepare file paths
    price_paths_file = OUTPUT_FILE_NPZ.replace('.npz', '_price_paths.npy')
    metadata_file = OUTPUT_FILE_NPZ.replace('.npz', '_metadata.npz')
    
    # Pre-convert arrays in parallel using ThreadPoolExecutor (I/O-bound operations)
    from concurrent.futures import ThreadPoolExecutor
    
    def convert_array(data):
        """Helper function to convert array to target type."""
        array, target_type = data
        return array.astype(target_type)
    
    print("  Pre-converting arrays in parallel...")
    prep_start = time.time()
    
    # Prepare conversion tasks
    conversion_tasks = [
        (all_scenarios_data, np.float32),
        (all_starting_pcts, np.float32),
        (all_starting_prices, np.float32),
    ]
    
    # Convert arrays in parallel
    if MULTIPROCESSING_AVAILABLE:
        with ThreadPoolExecutor(max_workers=min(3, NUM_CPUS)) as executor:
            converted_arrays = list(executor.map(convert_array, conversion_tasks))
        price_paths_converted, starting_pcts_converted, starting_prices_converted = converted_arrays
    else:
        # Sequential fallback
        price_paths_converted = all_scenarios_data.astype(np.float32)
        starting_pcts_converted = all_starting_pcts.astype(np.float32)
        starting_prices_converted = all_starting_prices.astype(np.float32)
    
    prep_time = time.time() - prep_start
    print(f"  ✓ Array conversion completed in {prep_time:.2f} seconds")
    
    # Save price paths and metadata in parallel (independent operations)
    print(f"  Saving price paths and metadata in parallel...")
    save_start = time.time()
    
    def save_price_paths():
        """Save large price paths array."""
        np.save(price_paths_file, price_paths_converted)
        return os.path.getsize(price_paths_file) / (1024 * 1024)
    
    def save_metadata():
        """Save metadata."""
        np.savez_compressed(
            metadata_file,
            starting_price_pcts=starting_pcts_converted,
            starting_prices=starting_prices_converted,
            num_simulations=np.int32(NUM_SIMULATIONS),
            simulation_years=np.int32(SIMULATION_YEARS),
            total_months=np.int32(TOTAL_MONTHS),
            current_bitcoin_price=np.float32(CURRENT_BITCOIN_PRICE),
            num_scenarios=np.int32(NUM_SCENARIOS),
            distribution_mean=np.float32(DIST_MEAN),
            distribution_std=np.float32(DIST_STD),
            distribution_skew=np.float32(DIST_SKEW),
            distribution_kurtosis=np.float32(DIST_KURTOSIS),
            distribution_tail_weight=np.float32(DIST_TAIL_WEIGHT),
            distribution_asymmetry=np.float32(DIST_ASYMMETRY)
        )
        return os.path.getsize(metadata_file) / (1024 * 1024)
    
    # Execute saves in parallel
    if MULTIPROCESSING_AVAILABLE:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_paths = executor.submit(save_price_paths)
            future_meta = executor.submit(save_metadata)
            paths_file_size_mb = future_paths.result()
            meta_file_size_mb = future_meta.result()
    else:
        # Sequential fallback
        paths_file_size_mb = save_price_paths()
        meta_file_size_mb = save_metadata()
    
    save_time = time.time() - save_start
    print(f"  ✓ Price paths and metadata saved in {save_time:.2f} seconds")
    print(f"    - Price paths: {paths_file_size_mb:.2f} MB")
    print(f"    - Metadata: {meta_file_size_mb:.2f} MB")
    
    npz_export_time = time.time() - export_start
    total_file_size_mb = paths_file_size_mb + meta_file_size_mb
    
    print(f"\n✓ Successfully exported!")
    print(f"  Total export time: {npz_export_time:.2f} seconds")
    print(f"  Breakdown:")
    print(f"    - Array conversion: {prep_time:.2f} seconds")
    print(f"    - Price paths + metadata (parallel): {save_time:.2f} seconds")
    print(f"  Total scenarios: {NUM_SCENARIOS}")
    print(f"  Total simulations: {NUM_SCENARIOS * NUM_SIMULATIONS:,}")
    print(f"  Total data points: {NUM_SCENARIOS * NUM_SIMULATIONS * TOTAL_MONTHS:,}")
    print(f"\n  Output files:")
    print(f"    - Price paths: {price_paths_file}")
    print(f"    - Metadata: {metadata_file}")
    
    print(f"\nScenarios:")
    for i, scenario in enumerate(all_scenarios):
        print(f"  {i+1:2d}. {scenario['starting_price_pct']*100:+6.0f}%: ${scenario['starting_price']:,.2f}")
    
    # ========================================================================
    # Step 4: Generate Distribution Comparison Charts
    # ========================================================================
    print(f"\n{'='*70}")
    print("STEP 4: GENERATING DISTRIBUTION COMPARISON CHARTS")
    print(f"{'='*70}")
    print("Generating histogram comparison of empirical vs manual distribution...")
    
    min_return = btc_returns.min()
    max_return = btc_returns.max()
    range_extension = (max_return - min_return) * 0.2
    bin_min = min_return - range_extension
    bin_max = max_return + range_extension
    
    n_bins = 50
    bins = np.linspace(bin_min, bin_max, n_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    bin_width = bins[1] - bins[0]
    
    empirical_density, _ = np.histogram(btc_returns.values, bins=bins, density=True)
    
    manual_density = manual_distribution_pdf(
        bin_centers, DIST_MEAN, DIST_STD, DIST_SKEW, DIST_KURTOSIS,
        DIST_TAIL_WEIGHT, DIST_ASYMMETRY
    )
    
    manual_integral = np.sum(manual_density) * bin_width
    if manual_integral > 0:
        manual_density_normalized = manual_density / manual_integral
    else:
        manual_density_normalized = manual_density
    
    # Main comparison plot
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))
    
    ax1 = axes[0]
    ax1.hist(btc_returns.values, bins=bins, density=True, alpha=0.6,
             label='Empirical (Historical Data)', color='blue', edgecolor='black')
    ax1.plot(bin_centers, manual_density_normalized, 'r-', linewidth=2,
             label=f'Manual Distribution (μ={DIST_MEAN:.3f}, σ={DIST_STD:.3f}, skew={DIST_SKEW:.3f}, kurt={DIST_KURTOSIS:.3f})')
    ax1.set_xlabel('Monthly Log Return', fontsize=12)
    ax1.set_ylabel('Probability Density', fontsize=12)
    ax1.set_title('Empirical vs Manual Distribution Comparison', fontsize=14, fontweight='bold')
    ax1.legend(fontsize=11)
    ax1.grid(True, alpha=0.3)
    
    ax2 = axes[1]
    width = bin_width * 0.35
    ax2.bar(bin_centers - width/2, empirical_density, width,
            label='Empirical', alpha=0.7, color='blue', edgecolor='black')
    ax2.bar(bin_centers + width/2, manual_density_normalized, width,
            label='Manual Distribution', alpha=0.7, color='red', edgecolor='black')
    ax2.set_xlabel('Monthly Log Return', fontsize=12)
    ax2.set_ylabel('Probability Density', fontsize=12)
    ax2.set_title('Side-by-Side Comparison (50 bins)', fontsize=14, fontweight='bold')
    ax2.legend(fontsize=11)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, 'distribution_comparison.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✓ Saved: {output_path}")
    
    # Side-by-side comparisons with different bin counts
    dist_params = {
        'mean': DIST_MEAN, 'std': DIST_STD, 'skew': DIST_SKEW,
        'kurtosis': DIST_KURTOSIS, 'tail_weight': DIST_TAIL_WEIGHT,
        'asymmetry': DIST_ASYMMETRY
    }
    
    print("\nGenerating side-by-side comparison with 25 bins...")
    create_side_by_side_comparison(btc_returns, bin_min, bin_max, 25, dist_params, OUTPUT_DIR)
    
    print("\nGenerating side-by-side comparison with 10 bins...")
    create_side_by_side_comparison(btc_returns, bin_min, bin_max, 10, dist_params, OUTPUT_DIR)
    
    # Calculate and print statistics
    x_fine = np.linspace(bin_min, bin_max, 1000)
    pdf_fine = manual_distribution_pdf(x_fine, DIST_MEAN, DIST_STD, DIST_SKEW,
                                       DIST_KURTOSIS, DIST_TAIL_WEIGHT, DIST_ASYMMETRY)
    dx_fine = x_fine[1] - x_fine[0]
    pdf_fine = pdf_fine / (np.sum(pdf_fine) * dx_fine)
    
    mean_manual = np.trapz(x_fine * pdf_fine, x_fine)
    var_manual = np.trapz((x_fine - mean_manual)**2 * pdf_fine, x_fine)
    std_manual = np.sqrt(var_manual)
    skew_manual = np.trapz(((x_fine - mean_manual) / std_manual)**3 * pdf_fine, x_fine) if std_manual > 0 else 0
    kurt_manual = np.trapz(((x_fine - mean_manual) / std_manual)**4 * pdf_fine, x_fine) - 3 if std_manual > 0 else 0
    
    print("\n" + "=" * 70)
    print("DISTRIBUTION COMPARISON STATISTICS")
    print("=" * 70)
    print(f"Number of bins: {n_bins}")
    print(f"Bin width: {bin_width:.6f}")
    print(f"Return range: [{bin_min:.4f}, {bin_max:.4f}]")
    print(f"\nEmpirical distribution:")
    print(f"  Mean: {btc_returns.mean():.6f}")
    print(f"  Std: {btc_returns.std():.6f}")
    print(f"  Skewness: {btc_returns.skew():.3f}")
    print(f"  Kurtosis: {btc_returns.kurtosis():.3f}")
    print(f"\nManual Distribution (from parameters):")
    print(f"  Mean: {mean_manual:.6f}")
    print(f"  Std: {std_manual:.6f}")
    print(f"  Skewness: {skew_manual:.3f}")
    print(f"  Kurtosis: {kurt_manual:.3f}")
    print(f"\nManual Distribution Parameters:")
    print(f"  DIST_MEAN: {DIST_MEAN:.4f}")
    print(f"  DIST_STD: {DIST_STD:.4f}")
    print(f"  DIST_SKEW: {DIST_SKEW:.4f}")
    print(f"  DIST_KURTOSIS: {DIST_KURTOSIS:.4f}")
    print(f"  DIST_TAIL_WEIGHT: {DIST_TAIL_WEIGHT:.4f}")
    print(f"  DIST_ASYMMETRY: {DIST_ASYMMETRY:.4f}")
    print("=" * 70)
    
    print(f"\n{'='*70}")
    print("✓ ALL TASKS COMPLETED SUCCESSFULLY!")
    print(f"{'='*70}")
    print(f"Output files:")
    print(f"  - Price paths: {price_paths_file}")
    print(f"  - Metadata: {metadata_file}")
    print(f"  - Charts saved to: {OUTPUT_DIR}/")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()

