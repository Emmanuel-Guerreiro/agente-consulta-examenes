// One-shot seed script for Neo4j Browser / Cypher Shell
// - Creates constraints
// - Inserts baseline Topics, Documents (+Sections), and Exercises
// - Optionally creates a sample Student
// Note: vectors are NOT populated here; use scripts/vectorize_csv.py for embeddings.

// Constraints (safe if already exist)
CREATE CONSTRAINT student_legajo IF NOT EXISTS FOR (s:Student) REQUIRE s.legajo IS UNIQUE;
CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT exercise_id IF NOT EXISTS FOR (e:Exercise) REQUIRE e.id IS UNIQUE;

// Topics
MERGE (cpu:Topic {id:'topic_cpu'}) SET cpu.nombre='CPU';
MERGE (alg:Topic {id:'topic_alg'}) SET alg.nombre='Algoritmos';
MERGE (db:Topic  {id:'topic_db'})  SET db.nombre='Bases de Datos';

// Documents
MERGE (d1:Document {id:'doc_cpu_intro'})
  SET d1.nombre='Introducción a la CPU',
      d1.content='La CPU es la unidad central de procesamiento que ejecuta instrucciones de programas.';
MERGE (d1)-[:BELONGS_TO]->(cpu);

MERGE (d2:Document {id:'doc_alg_intro'})
  SET d2.nombre='Qué es un algoritmo',
      d2.content='Un algoritmo es un conjunto finito de pasos para resolver un problema específico.';
MERGE (d2)-[:BELONGS_TO]->(alg);

MERGE (d3:Document {id:'doc_db_intro'})
  SET d3.nombre='Introducción a Bases de Datos',
      d3.content='Una base de datos organiza datos de forma estructurada y permite consultas eficientes.';
MERGE (d3)-[:BELONGS_TO]->(db);

// Sections
MERGE (s1:Section {id:'sec_cpu_1'}) SET s1.content='La CPU contiene la ALU y la unidad de control.';    MERGE (d1)-[:HAS_SECTION]->(s1);
MERGE (s2:Section {id:'sec_cpu_2'}) SET s2.content='Los registros almacenan datos temporales.';          MERGE (d1)-[:HAS_SECTION]->(s2);
MERGE (s3:Section {id:'sec_alg_1'}) SET s3.content='Complejidad: analiza tiempo y espacio.';            MERGE (d2)-[:HAS_SECTION]->(s3);
MERGE (s4:Section {id:'sec_db_1'})  SET s4.content='Modelo relacional y SQL como lenguaje declarativo.'; MERGE (d3)-[:HAS_SECTION]->(s4);

// Exercises
MERGE (e1:Exercise {id:'ex_cpu_1'})
  SET e1.task='¿Qué es una CPU?',
      e1.answer='Es la unidad central de procesamiento que ejecuta instrucciones.',
      e1.difficulty=0.2;
MERGE (e1)-[:BELONGS_TO]->(cpu);

MERGE (e2:Exercise {id:'ex_cpu_2'})
  SET e2.task='Nombra dos componentes principales de la CPU.',
      e2.answer='La ALU y la unidad de control.',
      e2.difficulty=0.4;
MERGE (e2)-[:BELONGS_TO]->(cpu);

MERGE (e3:Exercise {id:'ex_alg_1'})
  SET e3.task='Define algoritmo.',
      e3.answer='Conjunto finito de pasos para resolver un problema.',
      e3.difficulty=0.2;
MERGE (e3)-[:BELONGS_TO]->(alg);

MERGE (e4:Exercise {id:'ex_db_1'})
  SET e4.task='¿Qué es SQL?',
      e4.answer='Un lenguaje declarativo para gestionar datos en bases de datos relacionales.',
      e4.difficulty=0.3;
MERGE (e4)-[:BELONGS_TO]->(db);

// Optional: a sample Student (created automatically by agent on first run, too)
MERGE (:Student {legajo:'47262'});

// Sample knowledge levels for the sample Student
MATCH (s:Student {legajo:'47262'})
MATCH (cpu:Topic {id:'topic_cpu'})
MATCH (alg:Topic {id:'topic_alg'})
MATCH (db:Topic  {id:'topic_db'})
MERGE (s)-[k1:KNOWS]->(cpu) SET k1.level = 0.4;
MERGE (s)-[k2:KNOWS]->(alg) SET k2.level = 0.2;
MERGE (s)-[k3:KNOWS]->(db)  SET k3.level = 0.1;

// ---------------------------------------------------------------------------
// Consistency fixes (idempotent)
// - Relabel any mistakenly created :Excercise nodes to :Exercise
// - Ensure difficulty is stored as float for all Exercise nodes
// - Re-merge BELONGS_TO edges for the seeded exercises (safe if they exist)
// ---------------------------------------------------------------------------
MATCH (x:Excercise) REMOVE x:Excercise SET x:Exercise;

MATCH (e:Exercise) WHERE e.difficulty IS NOT NULL
SET e.difficulty = toFloat(e.difficulty);

MATCH (cpu:Topic {id:'topic_cpu'})
MATCH (e1:Exercise {id:'ex_cpu_1'}) MERGE (e1)-[:BELONGS_TO]->(cpu);
MATCH (e2:Exercise {id:'ex_cpu_2'}) MERGE (e2)-[:BELONGS_TO]->(cpu);

MATCH (alg:Topic {id:'topic_alg'})
MATCH (e3:Exercise {id:'ex_alg_1'}) MERGE (e3)-[:BELONGS_TO]->(alg);

MATCH (db:Topic {id:'topic_db'})
MATCH (e4:Exercise {id:'ex_db_1'}) MERGE (e4)-[:BELONGS_TO]->(db);


