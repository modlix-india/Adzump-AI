import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from scipy import stats

# ============================================================================
# 1. LOAD & CLEAN DATA (Same as before)
# ============================================================================
# REPLACE WITH YOUR PATH
file_path = '/content/sample_data/Campaign_budget_analysis_data_export.csv'

df = pd.read_csv(file_path, header=2)

# Clean columns
cols_to_clean = ['Impr.', 'Clicks', 'Conversions', 'Cost', 'Search budget']
for col in cols_to_clean:
    if col in df.columns:
        df[col] = df[col].astype(str).str.replace(r'[₹,%]', '', regex=True).str.replace(',', '').astype(float)

# Rename
df = df.rename(columns={'Impr.': 'Impressions', 'Cost': 'Budget', 'Search budget': 'Budget'})

# Aggregate by Campaign
df_agg = df.groupby('Campaign')[['Impressions', 'Clicks', 'Conversions', 'Budget']].sum().reset_index()
df_agg = df_agg[df_agg['Budget'] > 0] # Remove zeros

# ============================================================================
# 2. VISUALIZE THE PEARSON CORRELATION LINES
# ============================================================================

def plot_correlation_line(data, x_col, y_col):
    plt.figure(figsize=(10, 6))
    
    # Calculate Pearson Correlation (r)
    r, p_value = stats.pearsonr(data[x_col], data[y_col])
    
    # Draw Scatter Plot + Regression Line
    # ci=None removes the shaded confidence interval for a cleaner line
    # line_kws makes the line red
    sns.regplot(x=x_col, y=y_col, data=data, ci=None, 
                line_kws={'color': 'red', 'linewidth': 2}, 
                scatter_kws={'alpha': 0.6, 's': 80})
    
    plt.title(f"{x_col} vs {y_col}\nCorrelation (r) = {r:.4f}", fontsize=14, fontweight='bold')
    plt.xlabel(f"{x_col} (Count)", fontsize=12)
    plt.ylabel(f"{y_col} (₹)", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.show()

print("1️⃣ STRONG CORRELATION (The line fits well)")
plot_correlation_line(df_agg, 'Clicks', 'Budget')

print("\n2️⃣ WEAK CORRELATION (The dots ignore the line)")
plot_correlation_line(df_agg, 'Impressions', 'Budget')

# ============================================================================
# 3. EXPLANATION OF THE PLOTS
# ============================================================================
print("-" * 60)
print("🔍 HOW TO READ THESE PLOTS:")
print("-" * 60)
print("1. THE RED LINE: This represents the 'Best Prediction' based on a linear model.")
print("2. THE DOTS: These are your actual campaigns.")
print("3. CLICKS PLOT (r=0.85): Notice how the dots hug the red line tight?")
print("   -> This means Clicks are a reliable predictor.")
print("4. IMPRESSIONS PLOT (r=0.28): Notice how the dots are far away from the line?")
print("   -> This is why we removed Impressions. The line is just a bad guess.")
