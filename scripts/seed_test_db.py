#!/usr/bin/env python3
"""Seed the test database with sample recipes, users, reviews, and meal plan entries."""

import json
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", "/data/recipes.db")


def get_monday_of_current_week():
    today = datetime.now().date()
    return today - timedelta(days=today.weekday())


def seed():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # --- Users ---
    users = [
        (1001, "100000000000000001", "test_chef", "Chef Tester", ""),
        (1002, "100000000000000002", "pasta_lover", "Pasta Lover", ""),
        (1003, "100000000000000003", "dessert_queen", "Dessert Queen", ""),
    ]
    cur.executemany(
        """INSERT OR REPLACE INTO users (id, discord_id, username, display_name, avatar, created_at, last_login)
           VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        users,
    )

    # --- Recipes ---
    recipes = [
        {
            "title": "Classic Spaghetti Carbonara",
            "creator": "Italian Grandma",
            "source_url": "https://example.com/carbonara",
            "platform": "tiktok",
            "servings": "4",
            "prep_time": "10 min",
            "cook_time": "20 min",
            "total_time": "30 min",
            "ingredients": json.dumps([
                {"text": "400g spaghetti", "section": ""},
                {"text": "200g guanciale, diced", "section": ""},
                {"text": "4 egg yolks", "section": ""},
                {"text": "100g Pecorino Romano, grated", "section": ""},
                {"text": "Black pepper to taste", "section": ""},
            ]),
            "instructions": json.dumps([
                "Bring a large pot of salted water to boil and cook spaghetti al dente.",
                "While pasta cooks, render guanciale in a cold pan over medium heat until crispy.",
                "Whisk egg yolks with grated Pecorino and black pepper.",
                "Drain pasta, reserving 1 cup pasta water.",
                "Toss hot pasta with guanciale off heat, then quickly stir in egg mixture.",
                "Add pasta water as needed for silky sauce. Serve immediately.",
            ]),
            "tips": "Never add cream. The silkiness comes from the egg and cheese emulsion.",
            "tags": json.dumps(["pasta", "italian", "quick", "comfort food"]),
            "image_url": "",
            "added_by": "Chef Tester",
        },
        {
            "title": "Perfect Reverse-Sear Ribeye",
            "creator": "Grill Master Mike",
            "source_url": "https://example.com/ribeye",
            "platform": "instagram",
            "servings": "2",
            "prep_time": "5 min",
            "cook_time": "45 min",
            "total_time": "50 min",
            "ingredients": json.dumps([
                {"text": "2 ribeye steaks, 1.5 inches thick", "section": ""},
                {"text": "Kosher salt", "section": ""},
                {"text": "Black pepper", "section": ""},
                {"text": "2 tbsp butter", "section": ""},
                {"text": "Fresh rosemary and thyme", "section": ""},
                {"text": "3 cloves garlic, smashed", "section": ""},
            ]),
            "instructions": json.dumps([
                "Season steaks generously with salt and pepper. Rest at room temp 30 min.",
                "Preheat oven to 275°F (135°C).",
                "Place steaks on a wire rack over a baking sheet. Bake until internal temp is 120°F.",
                "Heat cast iron skillet until smoking hot.",
                "Sear steaks 1 minute per side.",
                "Add butter, herbs, and garlic. Baste for 30 seconds.",
                "Rest 5 minutes before slicing.",
            ]),
            "tips": "Use a meat thermometer. Pull at 120°F for perfect medium-rare after searing.",
            "tags": json.dumps(["steak", "beef", "grilling", "date night"]),
            "image_url": "",
            "added_by": "Chef Tester",
        },
        {
            "title": "Miso Glazed Salmon",
            "creator": "Tokyo Kitchen",
            "source_url": "https://example.com/miso-salmon",
            "platform": "tiktok",
            "servings": "4",
            "prep_time": "10 min",
            "cook_time": "15 min",
            "total_time": "25 min",
            "ingredients": json.dumps([
                {"text": "4 salmon fillets", "section": ""},
                {"text": "3 tbsp white miso paste", "section": ""},
                {"text": "2 tbsp mirin", "section": ""},
                {"text": "1 tbsp soy sauce", "section": ""},
                {"text": "1 tbsp rice vinegar", "section": ""},
                {"text": "1 tsp sesame oil", "section": ""},
            ]),
            "instructions": json.dumps([
                "Mix miso, mirin, soy sauce, rice vinegar, and sesame oil.",
                "Coat salmon fillets with miso glaze. Marinate 30 min or overnight.",
                "Preheat broiler to high.",
                "Place salmon on a lined baking sheet.",
                "Broil 8-10 minutes until glaze caramelizes and fish flakes easily.",
                "Garnish with sesame seeds and sliced scallions.",
            ]),
            "tips": "Don't marinate longer than 24 hours or the miso will over-cure the fish.",
            "tags": json.dumps(["asian", "japanese", "seafood", "healthy", "quick"]),
            "image_url": "",
            "added_by": "Pasta Lover",
        },
        {
            "title": "Street-Style Birria Tacos",
            "creator": "Abuela's Kitchen",
            "source_url": "https://example.com/birria-tacos",
            "platform": "tiktok",
            "servings": "6",
            "prep_time": "30 min",
            "cook_time": "3 hours",
            "total_time": "3.5 hours",
            "ingredients": json.dumps([
                {"text": "3 lbs chuck roast, cubed", "section": "Meat"},
                {"text": "4 guajillo chiles, stemmed and seeded", "section": "Sauce"},
                {"text": "2 ancho chiles", "section": "Sauce"},
                {"text": "1 can diced tomatoes", "section": "Sauce"},
                {"text": "1 onion, quartered", "section": "Sauce"},
                {"text": "5 cloves garlic", "section": "Sauce"},
                {"text": "Corn tortillas", "section": "To Serve"},
                {"text": "Oaxaca cheese, shredded", "section": "To Serve"},
                {"text": "Cilantro, onion, lime", "section": "To Serve"},
            ]),
            "instructions": json.dumps([
                "Toast dried chiles in a dry pan until fragrant, about 2 minutes.",
                "Soak chiles in hot water for 20 minutes.",
                "Blend chiles with tomatoes, onion, garlic, and spices until smooth.",
                "Season beef with salt and pepper, sear in batches.",
                "Combine beef and sauce in a Dutch oven. Braise at 325°F for 3 hours.",
                "Shred beef. Dip tortillas in consommé and griddle with cheese.",
                "Fill with birria meat. Serve with consommé for dipping.",
            ]),
            "tips": "Save the consommé — it's liquid gold for dipping and soup.",
            "tags": json.dumps(["mexican", "tacos", "beef", "comfort food", "weekend project"]),
            "image_url": "",
            "added_by": "Chef Tester",
        },
        {
            "title": "Tiramisu",
            "creator": "Dolce Vita Bakery",
            "source_url": "https://example.com/tiramisu",
            "platform": "instagram",
            "servings": "8",
            "prep_time": "30 min",
            "cook_time": "0 min",
            "total_time": "4.5 hours",
            "ingredients": json.dumps([
                {"text": "6 egg yolks", "section": ""},
                {"text": "3/4 cup sugar", "section": ""},
                {"text": "500g mascarpone cheese", "section": ""},
                {"text": "2 cups heavy cream", "section": ""},
                {"text": "2 cups strong espresso, cooled", "section": ""},
                {"text": "3 tbsp coffee liqueur", "section": ""},
                {"text": "400g ladyfinger cookies", "section": ""},
                {"text": "Cocoa powder for dusting", "section": ""},
            ]),
            "instructions": json.dumps([
                "Whisk egg yolks and sugar until thick and pale, about 5 minutes.",
                "Fold in mascarpone until smooth.",
                "Whip heavy cream to stiff peaks and fold into mascarpone mixture.",
                "Combine espresso and coffee liqueur in a shallow dish.",
                "Quickly dip ladyfingers in coffee (don't soak!) and layer in a 9x13 dish.",
                "Spread half the cream mixture over ladyfingers.",
                "Repeat with another layer of dipped ladyfingers and remaining cream.",
                "Refrigerate at least 4 hours, preferably overnight.",
                "Dust generously with cocoa powder before serving.",
            ]),
            "tips": "The key is speed when dipping ladyfingers — too long and they turn to mush.",
            "tags": json.dumps(["dessert", "italian", "no-bake", "make ahead"]),
            "image_url": "",
            "added_by": "Dessert Queen",
        },
        {
            "title": "Pad Thai",
            "creator": "Bangkok Street Food",
            "source_url": "https://example.com/pad-thai",
            "platform": "tiktok",
            "servings": "2",
            "prep_time": "15 min",
            "cook_time": "10 min",
            "total_time": "25 min",
            "ingredients": json.dumps([
                {"text": "200g rice noodles", "section": ""},
                {"text": "200g shrimp, peeled", "section": ""},
                {"text": "2 eggs", "section": ""},
                {"text": "3 tbsp tamarind paste", "section": "Sauce"},
                {"text": "2 tbsp fish sauce", "section": "Sauce"},
                {"text": "1 tbsp palm sugar", "section": "Sauce"},
                {"text": "Bean sprouts, peanuts, lime", "section": "Garnish"},
            ]),
            "instructions": json.dumps([
                "Soak rice noodles in warm water 30 minutes until pliable. Drain.",
                "Mix tamarind paste, fish sauce, and palm sugar for the sauce.",
                "Heat wok over high heat. Cook shrimp 2 minutes, set aside.",
                "Scramble eggs in wok, push to side.",
                "Add noodles and sauce. Toss constantly for 2 minutes.",
                "Add shrimp back. Toss with bean sprouts.",
                "Serve with crushed peanuts, lime wedge, and chili flakes.",
            ]),
            "tips": "High heat and fast tossing are essential. Don't overcrowd the wok.",
            "tags": json.dumps(["asian", "thai", "noodles", "quick", "seafood"]),
            "image_url": "",
            "added_by": "Pasta Lover",
        },
        {
            "title": "Chocolate Lava Cake",
            "creator": "Pastry Chef Pierre",
            "source_url": "https://example.com/lava-cake",
            "platform": "instagram",
            "servings": "4",
            "prep_time": "15 min",
            "cook_time": "12 min",
            "total_time": "27 min",
            "ingredients": json.dumps([
                {"text": "200g dark chocolate (70%)", "section": ""},
                {"text": "100g butter", "section": ""},
                {"text": "2 whole eggs + 2 egg yolks", "section": ""},
                {"text": "1/4 cup sugar", "section": ""},
                {"text": "2 tbsp flour", "section": ""},
                {"text": "Pinch of salt", "section": ""},
            ]),
            "instructions": json.dumps([
                "Preheat oven to 425°F. Butter and flour 4 ramekins.",
                "Melt chocolate and butter together. Let cool slightly.",
                "Whisk eggs, yolks, and sugar until thick.",
                "Fold chocolate mixture into eggs. Add flour and salt.",
                "Divide among ramekins. Can refrigerate up to 8 hours at this point.",
                "Bake 12-14 minutes until edges are set but center jiggles.",
                "Let rest 1 minute, then invert onto plates. Serve immediately.",
            ]),
            "tips": "Timing is everything — 1 minute too long and you lose the molten center.",
            "tags": json.dumps(["dessert", "chocolate", "french", "date night", "quick"]),
            "image_url": "",
            "added_by": "Dessert Queen",
        },
        {
            "title": "Korean Fried Chicken Wings",
            "creator": "Seoul Food",
            "source_url": "https://example.com/korean-chicken",
            "platform": "tiktok",
            "servings": "4",
            "prep_time": "20 min",
            "cook_time": "25 min",
            "total_time": "45 min",
            "ingredients": json.dumps([
                {"text": "2 lbs chicken wings", "section": ""},
                {"text": "1 cup potato starch", "section": ""},
                {"text": "Oil for frying", "section": ""},
                {"text": "3 tbsp gochujang", "section": "Sauce"},
                {"text": "2 tbsp soy sauce", "section": "Sauce"},
                {"text": "3 tbsp honey", "section": "Sauce"},
                {"text": "1 tbsp rice vinegar", "section": "Sauce"},
                {"text": "4 cloves garlic, minced", "section": "Sauce"},
                {"text": "Sesame seeds, scallions", "section": "Garnish"},
            ]),
            "instructions": json.dumps([
                "Pat wings dry. Coat in potato starch, shaking off excess.",
                "Heat oil to 350°F. Fry wings 10 minutes until cooked through. Drain.",
                "Increase oil to 375°F. Double-fry wings 3-4 minutes until extra crispy.",
                "While frying, combine gochujang, soy sauce, honey, vinegar, and garlic in a pan.",
                "Simmer sauce until slightly thickened.",
                "Toss crispy wings in sauce. Top with sesame seeds and scallions.",
            ]),
            "tips": "Double-frying is the secret to shatteringly crispy wings that stay crunchy.",
            "tags": json.dumps(["asian", "korean", "chicken", "appetizer", "spicy"]),
            "image_url": "",
            "added_by": "Chef Tester",
        },
        {
            "title": "Fresh Guacamole",
            "creator": "Mexico City Eats",
            "source_url": "https://example.com/guacamole",
            "platform": "tiktok",
            "servings": "4",
            "prep_time": "10 min",
            "cook_time": "0 min",
            "total_time": "10 min",
            "ingredients": json.dumps([
                {"text": "3 ripe avocados", "section": ""},
                {"text": "1 lime, juiced", "section": ""},
                {"text": "1/2 red onion, finely diced", "section": ""},
                {"text": "2 Roma tomatoes, diced", "section": ""},
                {"text": "1 jalapeño, minced", "section": ""},
                {"text": "1/4 cup fresh cilantro, chopped", "section": ""},
                {"text": "Salt to taste", "section": ""},
            ]),
            "instructions": json.dumps([
                "Halve avocados and remove pits. Scoop flesh into a bowl.",
                "Add lime juice and salt. Mash to desired consistency.",
                "Fold in onion, tomatoes, jalapeño, and cilantro.",
                "Taste and adjust salt and lime.",
                "Serve immediately with tortilla chips.",
            ]),
            "tips": "Leave an avocado pit in the bowl to slow browning if not serving immediately.",
            "tags": json.dumps(["mexican", "appetizer", "vegan", "quick", "healthy"]),
            "image_url": "",
            "added_by": "Pasta Lover",
        },
        {
            "title": "Creamy Tuscan Chicken",
            "creator": "Home Cook Hannah",
            "source_url": "https://example.com/tuscan-chicken",
            "platform": "instagram",
            "servings": "4",
            "prep_time": "10 min",
            "cook_time": "25 min",
            "total_time": "35 min",
            "ingredients": json.dumps([
                {"text": "4 chicken thighs, boneless skinless", "section": ""},
                {"text": "1 cup heavy cream", "section": ""},
                {"text": "1/2 cup sun-dried tomatoes, sliced", "section": ""},
                {"text": "2 cups fresh spinach", "section": ""},
                {"text": "1/2 cup Parmesan, grated", "section": ""},
                {"text": "4 cloves garlic, minced", "section": ""},
                {"text": "1 tsp Italian seasoning", "section": ""},
            ]),
            "instructions": json.dumps([
                "Season chicken with salt, pepper, and Italian seasoning.",
                "Sear chicken in olive oil 5-6 minutes per side. Remove and set aside.",
                "In the same pan, sauté garlic 30 seconds.",
                "Add heavy cream, sun-dried tomatoes, and Parmesan. Stir until smooth.",
                "Add spinach and cook until wilted.",
                "Return chicken to pan. Simmer 5 minutes until sauce thickens.",
                "Serve over pasta or with crusty bread.",
            ]),
            "tips": "Use chicken thighs — they stay juicier than breasts in the cream sauce.",
            "tags": json.dumps(["chicken", "italian", "comfort food", "one-pan", "quick"]),
            "image_url": "",
            "added_by": "Chef Tester",
        },
    ]

    columns = [
        "title", "creator", "source_url", "platform", "servings",
        "prep_time", "cook_time", "total_time", "ingredients", "instructions",
        "tips", "tags", "image_url", "added_by",
    ]
    placeholders = ", ".join(["?"] * len(columns))
    col_str = ", ".join(columns)

    for recipe in recipes:
        values = [recipe[col] for col in columns]
        cur.execute(f"INSERT INTO recipes ({col_str}) VALUES ({placeholders})", values)

    # --- Reviews ---
    reviews = [
        (1, 1002, 5, "Absolutely perfect carbonara! The egg emulsion was silky."),
        (1, 1003, 4, "Great recipe but I prefer a bit more pepper."),
        (2, 1002, 5, "Best steak method ever. Restaurant quality at home."),
        (3, 1001, 5, "The miso glaze caramelizes beautifully."),
        (4, 1003, 4, "Amazing birria but takes a while. Worth the effort!"),
        (5, 1001, 5, "Perfect tiramisu. Made it for a dinner party — huge hit."),
        (5, 1002, 4, "Delicious! I added a bit more coffee liqueur."),
        (7, 1001, 5, "Molten center was perfect at exactly 12 minutes."),
        (8, 1002, 5, "The double-fry technique is a game changer!"),
        (10, 1003, 4, "So creamy and comforting. My family loved it."),
    ]
    for recipe_id, user_id, rating, comment in reviews:
        cur.execute(
            """INSERT OR REPLACE INTO reviews (recipe_id, user_id, rating, comment, created_at, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (recipe_id, user_id, rating, comment),
        )

    # --- Meal Plan (current week) ---
    monday = get_monday_of_current_week()
    meal_plan_entries = [
        (1, (monday + timedelta(days=0)).isoformat(), 1001, "Chef Tester", None, None),
        (3, (monday + timedelta(days=1)).isoformat(), 1002, "Pasta Lover", None, None),
        (10, (monday + timedelta(days=2)).isoformat(), 1001, "Chef Tester", None, None),
        (4, (monday + timedelta(days=3)).isoformat(), 1001, "Chef Tester", None, None),
        (None, (monday + timedelta(days=4)).isoformat(), 1003, "Dessert Queen", "Pizza night 🍕", "🍕"),
        (5, (monday + timedelta(days=5)).isoformat(), 1003, "Dessert Queen", None, None),
        (2, (monday + timedelta(days=6)).isoformat(), 1001, "Chef Tester", None, None),
    ]
    for recipe_id, date, user_id, name, quick_text, quick_emoji in meal_plan_entries:
        cur.execute(
            """INSERT INTO meal_plan (recipe_id, date, added_by_user_id, added_by_name, quick_plan_text, quick_plan_emoji, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (recipe_id, date, user_id, name, quick_text, quick_emoji),
        )

    conn.commit()
    conn.close()

    print("✅ Test database seeded successfully!")
    print(f"   📖 {len(recipes)} recipes")
    print(f"   👤 {len(users)} test users")
    print(f"   ⭐ {len(reviews)} reviews")
    print(f"   📅 {len(meal_plan_entries)} meal plan entries (week of {monday.isoformat()})")


if __name__ == "__main__":
    seed()
