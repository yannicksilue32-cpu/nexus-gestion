NEXUS GESTION — MIGRATION SQLITE -> POSTGRESQL + RENDER
========================================================

FICHIERS
--------
app.py                         Application complète (SQLite local / PostgreSQL en ligne)
db_compat.py                  Couche de compatibilité SQLite/PostgreSQL
auth.py                       Authentification compatible avec les deux bases
migrate_sqlite_to_postgres.py Migration de database.db vers PostgreSQL
nexus_prix.py                 Moteur Nexus Prix
nexus_simulateur.py           Moteur Nexus Simulateur Business
nexus_prix.html               Interface Nexus Prix
nexus_simulateur.html         Interface Nexus Simulateur Business
base_nouveau.html             Base HTML avec les modules Nexus
requirements.txt              Dépendances production
render.yaml                   Blueprint Render Web + PostgreSQL
.gitignore                    Fichiers à exclure de Git

1) SAUVEGARDE
-------------
Conservez une copie de D:\NEXUS GESTION\database.db.
Ne supprimez pas la base SQLite avant d'avoir vérifié la migration.

2) INSTALLATION LOCALE
----------------------
D:\python.exe -m pip install -r requirements.txt

3) CREER POSTGRESQL
-------------------
Créez une base PostgreSQL puis récupérez sa DATABASE_URL.

4) MIGRER LES DONNEES
----------------------
Dans CMD Windows :

set DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
D:\python.exe migrate_sqlite_to_postgres.py

La migration ne modifie pas database.db.

5) TESTER NEXUS GESTION SUR POSTGRESQL EN LOCAL
------------------------------------------------
Toujours dans le même CMD :

set DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
D:\python.exe app.py

L'application détecte DATABASE_URL et utilise PostgreSQL.
Sans DATABASE_URL, elle continue à utiliser database.db.

6) TESTER LA BASE
------------------
Ouvrez :
http://127.0.0.1:5000/health

Le JSON doit indiquer :
"backend": "PostgreSQL"

7) DEPLOIEMENT RENDER
---------------------
Poussez ces fichiers sur GitHub, puis connectez le dépôt à Render.
Le render.yaml prépare le Web Service et PostgreSQL et injecte DATABASE_URL.

Build Command :
pip install -r requirements.txt

Start Command :
gunicorn app:app

8) IMPORTANT
------------
Le render.yaml fourni utilise les plans Free pour un premier test.
Le PostgreSQL Free de Render expire après 30 jours : pour une vraie
utilisation commerciale, passez à un plan PostgreSQL payant avant expiration.

9) NE PAS ENVOYER
-----------------
database.db
.env
NEXUS_SECRET_KEY
les mots de passe PostgreSQL

10) APRES VALIDATION
--------------------
Quand la version PostgreSQL fonctionne en local et sur Render :
- gardez database.db comme sauvegarde historique ;
- utilisez PostgreSQL comme base principale en ligne ;
- connectez ensuite Nexus Prix, Nexus Simulateur Business et Nexus Intelligence.
