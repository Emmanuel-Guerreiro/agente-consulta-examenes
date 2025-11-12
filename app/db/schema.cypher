// Constraints
CREATE CONSTRAINT student_legajo IF NOT EXISTS FOR (s:Student) REQUIRE s.legajo IS UNIQUE;
CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE;
CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT exercise_id IF NOT EXISTS FOR (e:Exercise) REQUIRE e.id IS UNIQUE;

// Vector indexes are created dynamically by code after detecting embedding dimensions.
// Fallback approach is in-app similarity computation if vector indexes are unavailable.


