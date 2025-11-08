from flask import Flask, render_template, request
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import io, base64, random

app = Flask(__name__)

def fig_to_base64():
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close()
    return data

@app.route('/', methods=['GET', 'POST'])
def index():
    action = request.form.get('action')
    chart_data = {}
    message = None

    if action == 'insights':
        # create sample dataset
        df = pd.DataFrame({
            'Diet': ['Keto', 'Vegan', 'Low Carb', 'Mediterranean'],
            'Calories': [random.randint(1800, 2400) for _ in range(4)],
            'Protein': [random.randint(50, 110) for _ in range(4)],
            'Carbs': [random.randint(100, 300) for _ in range(4)],
            'Fat': [random.randint(40, 90) for _ in range(4)]
        })

        # --- Bar chart ---
        plt.figure(figsize=(6,4))
        sns.barplot(x='Diet', y='Calories', data=df, palette='Blues_d')
        plt.title('Average Macronutrient Content by Diet Type')
        chart_data['bar'] = fig_to_base64()

        # --- Scatter plot ---
        plt.figure(figsize=(5,4))
        sns.scatterplot(x='Protein', y='Carbs', data=df, hue='Diet', s=100)
        plt.title('Nutrient Relationship: Protein vs Carbs')
        chart_data['scatter'] = fig_to_base64()

        # --- Heatmap ---
        plt.figure(figsize=(4,3))
        sns.heatmap(df[['Calories','Protein','Carbs','Fat']].corr(), annot=True, cmap='coolwarm')
        plt.title('Nutrient Correlations')
        chart_data['heatmap'] = fig_to_base64()

        # --- Pie chart ---
        plt.figure(figsize=(4,4))
        plt.pie(df['Calories'], labels=df['Diet'], autopct='%1.1f%%', startangle=140)
        plt.title('Recipe Distribution by Diet Type')
        chart_data['pie'] = fig_to_base64()

    elif action == 'recipes':
        message = [
            '🥗 Avocado Salad (Keto)',
            '🌯 Tofu Wrap (Vegan)',
            '🍗 Grilled Chicken (Low Carb)',
            '🍝 Mediterranean Pasta'
        ]
    elif action == 'clusters':
        message = [
            'Cluster 1: High Protein / Low Carb',
            'Cluster 2: Balanced Diet',
            'Cluster 3: High Carb / Moderate Fat'
        ]

    return render_template('insights.html', charts=chart_data, message=message)

if __name__ == '__main__':
    app.run(debug=True)
