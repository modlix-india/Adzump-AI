"""
Campaign Budget Prediction Model
=================================
This notebook uses Random Forest and XGBoost to predict campaign budgets
Better than Linear Regression for non-linear, real-world campaign data
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split, cross_val_score, cross_validate
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, mean_absolute_percentage_error
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PART 1: DATA LOADING & CLEANING (Keep your existing code)
# ============================================================================

print("="*70)
print("STEP 1: Loading and Cleaning Data")
print("="*70)

# Load CSV (adjust path as needed)
csv_file_path = '/content/sample_data/Campaign_budget_analysis_data_export.csv'
campaign_data = pd.read_csv(csv_file_path, header=2)

# Rename columns
campaign_data.rename(columns={'Impr.': 'Impressions'}, inplace=True)

# Clean numeric columns
campaign_data['Impressions'] = pd.to_numeric(
    campaign_data['Impressions'].astype(str).str.replace(',', '', regex=False),
    errors='coerce'
)
campaign_data['CTR'] = pd.to_numeric(
    campaign_data['CTR'].astype(str).str.replace('%', '', regex=False),
    errors='coerce'
)
campaign_data['Day'] = pd.to_datetime(campaign_data['Day'], errors='coerce')

print(f"✓ Loaded {len(campaign_data):,} daily records")
print(f"✓ Date range: {campaign_data['Day'].min()} to {campaign_data['Day'].max()}")

# ============================================================================
# PART 2: AGGREGATE BY CAMPAIGN
# ============================================================================

print("\n" + "="*70)
print("STEP 2: Aggregating Data by Campaign")
print("="*70)

campaign_agg = campaign_data.groupby('Campaign').agg(
    TotalImpressions=('Impressions', 'sum'),
    TotalClicks=('Clicks', 'sum'),
    TotalConversions=('Conversions', 'sum'),
    TotalBudget=('Budget', 'sum')
).reset_index()

print(f"✓ Aggregated to {len(campaign_agg)} unique campaigns")
print(f"\nBudget Statistics:")
print(f"  Min:    ₹{campaign_agg['TotalBudget'].min():,.0f}")
print(f"  Median: ₹{campaign_agg['TotalBudget'].median():,.0f}")
print(f"  Mean:   ₹{campaign_agg['TotalBudget'].mean():,.0f}")
print(f"  Max:    ₹{campaign_agg['TotalBudget'].max():,.0f}")

# ============================================================================
# PART 3: OUTLIER DETECTION & HANDLING
# ============================================================================

print("\n" + "="*70)
print("STEP 3: Outlier Analysis")
print("="*70)

Q1 = campaign_agg['TotalBudget'].quantile(0.25)
Q3 = campaign_agg['TotalBudget'].quantile(0.75)
IQR = Q3 - Q1
outlier_threshold = Q3 + 1.5 * IQR

outliers = campaign_agg[campaign_agg['TotalBudget'] > outlier_threshold]
print(f"✓ Found {len(outliers)} outlier campaigns (budget > ₹{outlier_threshold:,.0f})")

if len(outliers) > 0:
    print("\nOutlier Campaigns:")
    for idx, row in outliers.iterrows():
        print(f"  • {row['Campaign'][:50]}: ₹{row['TotalBudget']:,.0f}")

# OPTION: Remove outliers for more stable model
# Uncomment next line if you want to remove outliers
# campaign_agg = campaign_agg[campaign_agg['TotalBudget'] <= outlier_threshold]
# print(f"\n✓ Removed outliers. New dataset size: {len(campaign_agg)} campaigns")

# ============================================================================
# PART 4: PREPARE FEATURES (NO CTR - Only 3 features)
# ============================================================================

print("\n" + "="*70)
print("STEP 4: Preparing Features")
print("="*70)

# Features: Only TotalImpressions, TotalClicks, TotalConversions
X = campaign_agg[['TotalImpressions', 'TotalClicks', 'TotalConversions']]
y = campaign_agg['TotalBudget']

print(f"✓ Feature matrix shape: {X.shape}")
print(f"✓ Target variable shape: {y.shape}")
print(f"\nFeatures used:")
for i, col in enumerate(X.columns, 1):
    print(f"  {i}. {col}")

# Check for missing values
if X.isnull().sum().sum() > 0 or y.isnull().sum() > 0:
    print("\n⚠ WARNING: Missing values detected. Filling with 0...")
    X = X.fillna(0)
    y = y.fillna(y.median())

# ============================================================================
# PART 5: TRAIN-TEST SPLIT
# ============================================================================

print("\n" + "="*70)
print("STEP 5: Splitting Data")
print("="*70)

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

print(f"✓ Training set: {len(X_train)} campaigns")
print(f"✓ Test set:     {len(X_test)} campaigns")

# ============================================================================
# PART 6: MODEL TRAINING - RANDOM FOREST
# ============================================================================

print("\n" + "="*70)
print("STEP 6: Training Random Forest Model")
print("="*70)

rf_model = RandomForestRegressor(
    n_estimators=100,
    max_depth=10,
    min_samples_split=5,
    min_samples_leaf=2,
    random_state=42,
    n_jobs=-1
)

rf_model.fit(X_train, y_train)
print("✓ Random Forest trained successfully")

# ============================================================================
# PART 7: MODEL TRAINING - XGBOOST (if available)
# ============================================================================

print("\n" + "="*70)
print("STEP 7: Training XGBoost Model")
print("="*70)

try:
    import xgboost as xgb
    
    xgb_model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42,
        n_jobs=-1
    )
    
    xgb_model.fit(X_train, y_train)
    print("✓ XGBoost trained successfully")
    xgb_available = True
    
except ImportError:
    print("⚠ XGBoost not installed. Install with: pip install xgboost")
    print("  Continuing with Random Forest only...")
    xgb_available = False

# ============================================================================
# PART 8: MODEL EVALUATION - CROSS VALIDATION
# ============================================================================

print("\n" + "="*70)
print("STEP 8: Cross-Validation (5-Fold) - RELIABLE METRICS")
print("="*70)

scoring = {
    'r2': 'r2',
    'mae': 'neg_mean_absolute_error',
    'rmse': 'neg_root_mean_squared_error'
}

# Random Forest CV
rf_cv_scores = cross_validate(rf_model, X, y, cv=5, scoring=scoring, n_jobs=-1)

print("\n📊 RANDOM FOREST (Cross-Validation):")
print(f"  R² Score:  {rf_cv_scores['test_r2'].mean():.4f} (± {rf_cv_scores['test_r2'].std():.4f})")
print(f"  MAE:       ₹{-rf_cv_scores['test_mae'].mean():,.0f} (± ₹{rf_cv_scores['test_mae'].std():,.0f})")
print(f"  RMSE:      ₹{-rf_cv_scores['test_rmse'].mean():,.0f}")

# XGBoost CV (if available)
if xgb_available:
    xgb_cv_scores = cross_validate(xgb_model, X, y, cv=5, scoring=scoring, n_jobs=-1)
    
    print("\n📊 XGBOOST (Cross-Validation):")
    print(f"  R² Score:  {xgb_cv_scores['test_r2'].mean():.4f} (± {xgb_cv_scores['test_r2'].std():.4f})")
    print(f"  MAE:       ₹{-xgb_cv_scores['test_mae'].mean():,.0f} (± ₹{xgb_cv_scores['test_mae'].std():,.0f})")
    print(f"  RMSE:      ₹{-xgb_cv_scores['test_rmse'].mean():,.0f}")

# ============================================================================
# PART 9: TEST SET EVALUATION
# ============================================================================

print("\n" + "="*70)
print("STEP 9: Test Set Performance")
print("="*70)

# Random Forest predictions
rf_pred = rf_model.predict(X_test)
rf_r2 = r2_score(y_test, rf_pred)
rf_mae = mean_absolute_error(y_test, rf_pred)
rf_rmse = np.sqrt(mean_squared_error(y_test, rf_pred))
rf_mape = mean_absolute_percentage_error(y_test, rf_pred) * 100

print("\n📊 RANDOM FOREST (Test Set):")
print(f"  R² Score:  {rf_r2:.4f}")
print(f"  MAE:       ₹{rf_mae:,.0f}")
print(f"  RMSE:      ₹{rf_rmse:,.0f}")
print(f"  MAPE:      {rf_mape:.2f}%")

# XGBoost predictions (if available)
if xgb_available:
    xgb_pred = xgb_model.predict(X_test)
    xgb_r2 = r2_score(y_test, xgb_pred)
    xgb_mae = mean_absolute_error(y_test, xgb_pred)
    xgb_rmse = np.sqrt(mean_squared_error(y_test, xgb_pred))
    xgb_mape = mean_absolute_percentage_error(y_test, xgb_pred) * 100
    
    print("\n📊 XGBOOST (Test Set):")
    print(f"  R² Score:  {xgb_r2:.4f}")
    print(f"  MAE:       ₹{xgb_mae:,.0f}")
    print(f"  RMSE:      ₹{xgb_rmse:,.0f}")
    print(f"  MAPE:      {xgb_mape:.2f}%")

# Select best model
if xgb_available and xgb_r2 > rf_r2:
    best_model = xgb_model
    best_model_name = "XGBoost"
    best_pred = xgb_pred
else:
    best_model = rf_model
    best_model_name = "Random Forest"
    best_pred = rf_pred

print(f"\n🏆 BEST MODEL: {best_model_name}")

# ============================================================================
# PART 10: FEATURE IMPORTANCE
# ============================================================================

print("\n" + "="*70)
print("STEP 10: Feature Importance Analysis")
print("="*70)

if hasattr(best_model, 'feature_importances_'):
    importance_df = pd.DataFrame({
        'Feature': X.columns,
        'Importance': best_model.feature_importances_
    }).sort_values('Importance', ascending=False)
    
    print("\n📊 Feature Importance (What drives budget?):")
    for idx, row in importance_df.iterrows():
        print(f"  {row['Feature']:20s}: {row['Importance']:.4f} ({row['Importance']*100:.1f}%)")
    
    # Visualize
    plt.figure(figsize=(10, 6))
    plt.barh(importance_df['Feature'], importance_df['Importance'])
    plt.xlabel('Importance Score')
    plt.title(f'Feature Importance - {best_model_name}')
    plt.tight_layout()
    plt.show()

# ============================================================================
# PART 11: ACTUAL VS PREDICTED VISUALIZATION
# ============================================================================

print("\n" + "="*70)
print("STEP 11: Visualization")
print("="*70)

comparison_df = pd.DataFrame({
    'Actual Budget': y_test.values,
    'Predicted Budget': best_pred,
    'Error': y_test.values - best_pred,
    'Error %': ((y_test.values - best_pred) / y_test.values * 100)
})

print("\n📊 Sample Predictions:")
print(comparison_df.head(10).to_string(index=False))

# Scatter plot
fig, axes = plt.subplots(1, 2, figsize=(16, 6))

# Plot 1: Actual vs Predicted
axes[0].scatter(y_test, best_pred, alpha=0.6, s=100)
min_val = min(y_test.min(), best_pred.min())
max_val = max(y_test.max(), best_pred.max())
axes[0].plot([min_val, max_val], [min_val, max_val], 'r--', lw=2, label='Perfect Prediction')
axes[0].set_xlabel('Actual Budget (₹)', fontsize=12)
axes[0].set_ylabel('Predicted Budget (₹)', fontsize=12)
axes[0].set_title(f'Actual vs Predicted - {best_model_name}', fontsize=14)
axes[0].legend()
axes[0].grid(True, alpha=0.3)
axes[0].ticklabel_format(style='plain', axis='both')

# Plot 2: Residuals
axes[1].scatter(best_pred, comparison_df['Error'], alpha=0.6, s=100)
axes[1].axhline(y=0, color='r', linestyle='--', lw=2)
axes[1].set_xlabel('Predicted Budget (₹)', fontsize=12)
axes[1].set_ylabel('Prediction Error (₹)', fontsize=12)
axes[1].set_title('Residual Plot', fontsize=14)
axes[1].grid(True, alpha=0.3)
axes[1].ticklabel_format(style='plain', axis='both')

plt.tight_layout()
plt.show()

# ============================================================================
# PART 12: PREDICTION FUNCTION FOR NEW CAMPAIGNS
# ============================================================================

print("\n" + "="*70)
print("STEP 12: Making Predictions for New Campaigns")
print("="*70)

def predict_budget(impressions, clicks, conversions, model=best_model):
    """
    Predict budget for a new campaign
    
    Parameters:
    -----------
    impressions : int
        Expected total impressions
    clicks : int
        Expected total clicks
    conversions : float
        Expected total conversions
    model : trained model
        The model to use for prediction
    
    Returns:
    --------
    float : Predicted budget in ₹
    """
    new_data = pd.DataFrame({
        'TotalImpressions': [impressions],
        'TotalClicks': [clicks],
        'TotalConversions': [conversions]
    })
    
    prediction = model.predict(new_data)[0]
    return prediction

# Example predictions
print("\n📊 Example Predictions for New Campaigns:")
print("-" * 70)

test_campaigns = [
    {'name': 'Small Campaign', 'impressions': 5000, 'clicks': 250, 'conversions': 5},
    {'name': 'Medium Campaign', 'impressions': 25000, 'clicks': 1500, 'conversions': 50},
    {'name': 'Large Campaign', 'impressions': 100000, 'clicks': 5000, 'conversions': 200},
]

for camp in test_campaigns:
    pred_budget = predict_budget(
        camp['impressions'], 
        camp['clicks'], 
        camp['conversions']
    )
    print(f"\n{camp['name']}:")
    print(f"  Impressions:  {camp['impressions']:,}")
    print(f"  Clicks:       {camp['clicks']:,}")
    print(f"  Conversions:  {camp['conversions']:,}")
    print(f"  → Predicted Budget: ₹{pred_budget:,.2f}")

# ============================================================================
# PART 13: MODEL SAVING (Optional)
# ============================================================================

print("\n" + "="*70)
print("STEP 13: Model Saving")
print("="*70)

import joblib

# Save the best model
model_filename = f'campaign_budget_model_{best_model_name.lower().replace(" ", "_")}.pkl'
joblib.dump(best_model, model_filename)
print(f"✓ Model saved as: {model_filename}")

# To load later:
# loaded_model = joblib.load(model_filename)
# predictions = loaded_model.predict(new_data)

print("\n" + "="*70)
print("✅ PIPELINE COMPLETE!")
print("="*70)
print(f"\nBest Model: {best_model_name}")
print(f"Ready for production use!")
print(f"\nTo predict new campaigns, use:")
print(f"  predict_budget(impressions, clicks, conversions)")